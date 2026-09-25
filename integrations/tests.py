"""Unit tests for the integration packages: `integrations.blink` and
`integrations.bitlibera` (doc §6–§25).

All network access is faked: the WebSocket/HTTP transports never run here. The
tests pin the *contract* pieces: endpoint paths, GraphQL operation names, frame
builders, status translation, the error mapping AND the full payment flows the
Node reference consumes (create → poll → pay/cancel; OTP → execute → off-ramp →
order status), against the LIVE blink public schema (introspected 2026):
`lnInvoicePaymentStatusByPaymentRequest` (input-object arg), `lnAddress` on
`lnAddressPaymentSend`, cancel by `paymentHash`, `accountDefaultWallet { id,
currency }`, `LnInvoice` with no `cents` field.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from integrations.bitlibera import (
    endpoints,
    exceptions as bitlibera_exceptions,
)
from integrations.bitlibera.client import BitLiberaClient
from integrations.bitlibera.services import (
    BitLiberaService,
    ORDER_STATUS_MAP,
    translate_order_status,
)
from integrations.blink import mutations, queries, subscriptions as blink_subscriptions
from integrations.blink.client import BlinkClient
from integrations.blink.exceptions import BlinkAuthError, BlinkConfigError, BlinkGraphQLError
from integrations.blink.services import BlinkInvoice, BlinkService, translate_invoice_status


class FakeResponse:
    """Minimal requests-like response for the fake transports."""

    def __init__(
        self,
        body: Any,
        status_code: int = 200,
        json_error: bool = False,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("Not JSON")
        return self.body


class FakeSession:
    """Records the last request a client issued instead of hitting the network."""

    def __init__(self, responses: FakeResponse | list[FakeResponse]) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.responses[min(len(self.calls), len(self.responses)) - 1]

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record(url, kwargs)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record(url, kwargs)


# --------------------------------------------------------------------------- #
# Blink — documents (live-schema parity with the Node reference)                #
# --------------------------------------------------------------------------- #


class TestBlinkGraphQLDocuments:
    def test_query_operation_names_are_contract(self):
        assert "query AccountDefaultWallet" in queries.ACCOUNT_DEFAULT_WALLET_QUERY
        assert "query LnInvoicePaymentStatusByPaymentRequest" in (
            queries.LN_INVOICE_PAYMENT_STATUS_QUERY
        )
        assert "query RealtimePrice" in queries.REALTIME_PRICE_QUERY

    def test_mutation_operation_names_are_contract(self):
        assert "mutation LnInvoiceCreateOnBehalfOfRecipient" in mutations.LN_INVOICE_CREATE_MUTATION
        assert "mutation LnUsdInvoiceCreateOnBehalfOfRecipient" in (
            mutations.LN_USD_INVOICE_CREATE_MUTATION
        )
        assert "mutation LnInvoiceCancel" in mutations.LN_INVOICE_CANCEL_MUTATION
        assert "mutation LnInvoicePaymentSend" in mutations.LN_INVOICE_PAYMENT_SEND_MUTATION
        assert "mutation LnAddressPaymentSend" in mutations.LN_ADDRESS_PAYMENT_SEND_MUTATION

    def test_status_uses_input_object_and_real_operation(self):
        # The Node reference's `lnInvoicePaymentStatus` does NOT exist on the
        # live schema — the real operation takes `input: { paymentRequest }`.
        assert (
            "lnInvoicePaymentStatusByPaymentRequest(input: { paymentRequest: $paymentRequest })"
            in (queries.LN_INVOICE_PAYMENT_STATUS_QUERY)
        )
        assert "lnInvoicePaymentStatus(" not in queries.LN_INVOICE_PAYMENT_STATUS_QUERY
        assert "lnInvoicePaymentStatus(" not in blink_subscriptions.SUBSCRIPTION_INVOICE_STATUS

    def test_wallet_query_selects_id_and_currency(self):
        # Live PublicWallet exposes `id` + `currency` (not walletCurrency/balance).
        assert "id" in queries.ACCOUNT_DEFAULT_WALLET_QUERY
        assert "currency" in queries.ACCOUNT_DEFAULT_WALLET_QUERY

    def test_usd_mutation_never_selects_cents(self):
        # Live LnInvoice has no `cents` field — even for USD invoices.
        assert "cents" not in mutations.LN_USD_INVOICE_CREATE_MUTATION
        assert "paymentRequest" in mutations.LN_USD_INVOICE_CREATE_MUTATION

    def test_cancel_mutation_declares_cancel_input_by_hash(self):
        assert "LnInvoiceCancelInput" in mutations.LN_INVOICE_CANCEL_MUTATION
        assert "success" in mutations.LN_INVOICE_CANCEL_MUTATION

    def test_payment_send_mutation_input_type_is_live(self):
        # Type is LnInvoicePaymentInput on the live schema, not ...SendInput.
        assert "LnInvoicePaymentInput" in mutations.LN_INVOICE_PAYMENT_SEND_MUTATION


# --------------------------------------------------------------------------- #
# Blink — WebSocket frames & status translation                                 #
# --------------------------------------------------------------------------- #


class TestBlinkStatusTranslation:
    def test_canonical_mapping(self):
        assert translate_invoice_status("PAID") == "paid"
        assert translate_invoice_status("pending") == "pending"
        assert translate_invoice_status("EXPIRED") == "expired"

    def test_send_result_statuses_pass_through_lowercased(self):
        assert translate_invoice_status("SUCCESS") == "success"
        assert translate_invoice_status("ALREADY_PAID") == "already_paid"
        assert translate_invoice_status("FAILURE") == "failure"
        assert translate_invoice_status(None) == ""


class TestBlinkWebSocketFrames:
    def test_connection_init_without_key(self):
        assert blink_subscriptions.build_connection_init() == {
            "type": "connection_init",
            "payload": {},
        }

    def test_connection_init_with_key(self):
        frame = blink_subscriptions.build_connection_init("bl_abc")
        assert frame["payload"] == {"headers": {"X-API-KEY": "bl_abc"}}

    def test_subscribe_payload(self):
        payload = blink_subscriptions.build_subscribe_payload("lnbc1", "req-1")
        assert payload["id"] == "req-1"
        assert payload["type"] == "subscribe"
        assert "LnInvoicePaymentStatusByPaymentRequest" in payload["payload"]["query"]
        assert payload["payload"]["variables"] == {"paymentRequest": "lnbc1"}


class TestBlinkStatusMessageParsing:
    def test_next_frame_returns_status(self):
        message = {
            "type": "next",
            "payload": {"data": {"lnInvoicePaymentStatusByPaymentRequest": {"status": "PAID"}}},
        }
        assert blink_subscriptions.parse_status_message(message) == "PAID"

    def test_error_frame_raises(self):
        message = {"type": "error", "payload": [{"message": "Invoice expired."}]}
        with pytest.raises(blink_subscriptions.BlinkSubscriptionError):
            blink_subscriptions.parse_status_message(message)

    def test_complete_frame_raises(self):
        message = {"type": "complete"}
        with pytest.raises(blink_subscriptions.BlinkSubscriptionError):
            blink_subscriptions.parse_status_message(message)

    def test_missing_status_raises(self):
        message = {"type": "next", "payload": {"data": {}}}
        with pytest.raises(blink_subscriptions.BlinkSubscriptionError):
            blink_subscriptions.parse_status_message(message)


# --------------------------------------------------------------------------- #
# Blink — HTTP client                                                           #
# --------------------------------------------------------------------------- #


class TestBlinkClient:
    def test_missing_url_or_key_raises(self, monkeypatch):
        monkeypatch.delenv("BLINK_API_URL", raising=False)
        monkeypatch.delenv("BLINK_API_KEY", raising=False)
        with pytest.raises(BlinkConfigError):
            BlinkClient(url="", api_key="key-1")
        with pytest.raises(BlinkConfigError):
            BlinkClient(url="https://api.blink.sv/graphql", api_key="")

    def test_sends_graphql_payload_and_headers(self):
        session = FakeSession(FakeResponse({"data": {"accountDefaultWallet": {"id": "w1"}}}))
        client = BlinkClient(url="https://api.blink.sv/graphql", api_key="key-1", session=session)

        data = client.execute("query { hello }", {"a": 1}, operation_name="Hello")

        assert data == {"accountDefaultWallet": {"id": "w1"}}
        assert session.calls[-1][0] == "https://api.blink.sv/graphql"
        assert session.calls[-1][1]["headers"]["X-API-KEY"] == "key-1"
        assert session.calls[-1][1]["json"]["operationName"] == "Hello"
        assert session.calls[-1][1]["json"]["variables"] == {"a": 1}

    def test_graphql_errors_raise(self):
        session = FakeSession(FakeResponse({"errors": [{"message": "Unauthorized operation."}]}))
        client = BlinkClient(url="https://api.blink.sv/graphql", api_key="key-1", session=session)
        with pytest.raises(BlinkGraphQLError):
            client.execute("query { hello }")

    def test_http_401_raises_auth_error(self):
        session = FakeSession(FakeResponse({"errors": []}, status_code=401))
        client = BlinkClient(url="https://api.blink.sv/graphql", api_key="bad", session=session)
        with pytest.raises(BlinkAuthError):
            client.execute("query { hello }")


# --------------------------------------------------------------------------- #
# Blink — service layer                                                         #
# --------------------------------------------------------------------------- #


class _FakeBlinkClient:
    def __init__(self, responses: dict[str, Any] | list[dict[str, Any]]) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self, query: str, variables: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        self.executed.append((query, variables or {}))
        return self.responses[min(len(self.executed), len(self.responses)) - 1]


class TestBlinkService:
    def test_default_wallet(self):
        service = BlinkService(
            _FakeBlinkClient({"accountDefaultWallet": {"id": "w-btc", "currency": "BTC"}})
        )
        wallet = service.default_wallet("pro.fobos")
        assert wallet["id"] == "w-btc"
        assert wallet["currency"] == "BTC"

    def test_create_invoice_btc_parses_invoice(self):
        fake = _FakeBlinkClient(
            {
                "lnInvoiceCreateOnBehalfOfRecipient": {
                    "errors": [],
                    "invoice": {
                        "paymentRequest": "lnbc1",
                        "paymentHash": "h1",
                        "satoshis": 1000,
                        "paymentStatus": "PENDING",
                    },
                }
            }
        )
        service = BlinkService(fake, btc_wallet_id="w-btc")
        invoice = service.create_invoice_btc(1000)
        assert isinstance(invoice, BlinkInvoice)
        assert invoice.payment_request == "lnbc1"
        assert invoice.payment_hash == "h1"
        assert invoice.amount_sats == 1000
        assert invoice.status == "pending"
        assert fake.executed[-1][1] == {"input": {"amount": 1000, "recipientWalletId": "w-btc"}}

    def test_create_invoice_btc_requires_wallet(self):
        service = BlinkService(_FakeBlinkClient({}), btc_wallet_id="")
        with pytest.raises(BlinkConfigError):
            service.create_invoice_btc(1000)

    def test_invoice_status_polls_and_translates(self):
        fake = _FakeBlinkClient({"lnInvoicePaymentStatusByPaymentRequest": {"status": "PAID"}})
        service = BlinkService(fake, btc_wallet_id="w-btc")
        assert service.invoice_status("lnbc1") == "paid"

    def test_pay_invoice_translates_status(self):
        fake = _FakeBlinkClient({"lnInvoicePaymentSend": {"errors": [], "status": "SUCCESS"}})
        service = BlinkService(fake, btc_wallet_id="w-btc")
        assert service.pay_invoice("lnbc1", wallet_id="w-btc") == "success"

    def test_pay_lightning_address_uses_ln_address_field(self):
        fake = _FakeBlinkClient({"lnAddressPaymentSend": {"errors": [], "status": "SUCCESS"}})
        service = BlinkService(fake, btc_wallet_id="w-btc")
        assert service.pay_lightning_address("sats@blink.sv", 250, wallet_id="w-btc") == "success"
        variables = fake.executed[-1][1]
        assert variables == {
            "input": {"lnAddress": "sats@blink.sv", "amount": 250, "walletId": "w-btc"}
        }

    def test_cancel_invoice_uses_payment_hash(self):
        fake = _FakeBlinkClient({"lnInvoiceCancel": {"errors": [], "success": True}})
        service = BlinkService(fake, btc_wallet_id="w-btc")
        assert service.cancel_invoice("hash-1", wallet_id="w-btc") is True
        assert fake.executed[-1][1] == {"input": {"paymentHash": "hash-1", "walletId": "w-btc"}}

    def test_realtime_price(self):
        fake = _FakeBlinkClient(
            {"realtimePrice": {"btcSatPrice": {"base": 100000000, "offset": 7}}}
        )
        service = BlinkService(fake, btc_wallet_id="w-btc")
        price = service.realtime_price("USD")
        assert price["btcSatPrice"] == {"base": 100000000, "offset": 7}


# --------------------------------------------------------------------------- #
# Blink — end-to-end payment flow (reference consumption, fake transport)       #
# --------------------------------------------------------------------------- #


class TestBlinkPaymentFlow:
    """Replay the Node reference flow: create → monitor → pay → cancel.

    Each request/response pair mirrors the real API shapes so the services are
    exercised exactly as they would be against api.blink.sv.
    """

    def _service(self) -> tuple[BlinkService, FakeSession]:
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "data": {
                            "lnInvoiceCreateOnBehalfOfRecipient": {
                                "errors": [],
                                "invoice": {
                                    "paymentRequest": "lnbc1",
                                    "paymentHash": "h1",
                                    "satoshis": 1000,
                                    "paymentStatus": "PENDING",
                                },
                            }
                        }
                    }
                ),
                FakeResponse(
                    {"data": {"lnInvoicePaymentStatusByPaymentRequest": {"status": "PAID"}}}
                ),
                FakeResponse(
                    {"data": {"lnAddressPaymentSend": {"errors": [], "status": "SUCCESS"}}}
                ),
                FakeResponse({"data": {"lnInvoiceCancel": {"errors": [], "success": True}}}),
            ]
        )
        client = BlinkClient(url="https://api.blink.sv/graphql", api_key="key-1", session=session)
        return BlinkService(client, btc_wallet_id="w-btc"), session

    def test_full_lightning_cycle(self):
        service, session = self._service()

        invoice = service.create_invoice_btc(1000, memo="Paiement via Blink", expires_in_minutes=15)
        assert invoice.payment_request == "lnbc1"
        assert invoice.status == "pending"

        assert service.invoice_status(invoice.payment_request) == "paid"

        assert service.pay_lightning_address("sats@blink.sv", 1000) == "success"

        assert service.cancel_invoice(invoice.payment_hash) is True

        assert len(session.calls) == 4
        headers = session.calls[0][1]["headers"]
        assert headers["X-API-KEY"] == "key-1"


# --------------------------------------------------------------------------- #
# BitLibera — endpoints, translation, client, service                           #
# --------------------------------------------------------------------------- #


class TestBitLiberaEndpoints:
    def test_paths_are_contract(self):
        assert endpoints.ONRAMP_REQUEST_OTP == "/api/v1/onramp/request-otp"
        assert endpoints.ONRAMP_EXECUTE == "/api/v1/onramp/execute"
        assert endpoints.OFFRAMP_CREATE_INVOICE == "/api/v1/offramp/create-invoice"
        assert endpoints.ORDER_STATUS == "/api/v1/orders/{order_id}"


class TestBitLiberaStatusTranslation:
    def test_canonical_mapping(self):
        assert translate_order_status("PENDING_PAYMENT") == "pending"
        assert translate_order_status("PAID") == "paid"
        assert translate_order_status("COMPLETED") == "paid"
        assert translate_order_status("EXPIRED") == "expired"
        assert translate_order_status("failed") == "failed"

    def test_map_covers_documented_states(self):
        assert set(ORDER_STATUS_MAP) == {
            "PENDING_PAYMENT",
            "PENDING",
            "PAID",
            "COMPLETED",
            "SETTLED",
            "EXPIRED",
            "FAILED",
            "CANCELLED",
        }

    def test_unknown_passes_through_lowercased(self):
        assert translate_order_status("ON_HOLD") == "on_hold"


class TestBitLiberaClient:
    def test_missing_api_key_raises_config_error(self, monkeypatch):
        monkeypatch.delenv("BITLIBERA_API_KEY", raising=False)
        client = BitLiberaClient(base_url="https://exchanger.bitlibera.com", api_key="")
        with pytest.raises(bitlibera_exceptions.BitLiberaConfigError):
            client.get("/api/v1/orders/x")

    def test_post_sends_auth_header_and_body(self):
        session = FakeSession(FakeResponse({"success": True, "status": "ok"}))
        client = BitLiberaClient(
            base_url="https://exchanger.bitlibera.com",
            api_key="bl_live_1",
            session=session,
        )
        body = client.post("/api/v1/onramp/request-otp", {"phone": "+2571", "amount": 1000})
        assert body["success"] is True
        assert session.calls[-1][0] == "https://exchanger.bitlibera.com/api/v1/onramp/request-otp"
        assert session.calls[-1][1]["headers"]["x-api-key"] == "bl_live_1"
        assert session.calls[-1][1]["json"] == {"phone": "+2571", "amount": 1000}

    def test_success_false_raises_order_error(self):
        session = FakeSession(FakeResponse({"success": False, "message": "Bad order."}))
        client = BitLiberaClient(
            base_url="https://exchanger.bitlibera.com",
            api_key="bl_live_1",
            session=session,
        )
        with pytest.raises(bitlibera_exceptions.BitLiberaOrderError):
            client.post("/api/v1/onramp/execute", {})

    def test_http_401_raises_auth_error(self):
        session = FakeSession(FakeResponse({}, status_code=401))
        client = BitLiberaClient(
            base_url="https://exchanger.bitlibera.com",
            api_key="bad",
            session=session,
        )
        with pytest.raises(bitlibera_exceptions.BitLiberaAuthError):
            client.get("/api/v1/orders/x")


class _FakeBitLiberaClient:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.last_call: tuple[str, dict[str, Any]] = ("", {})

    def post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        self.last_call = (endpoint, data)
        return self.body

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_call = (endpoint, params or {})
        return self.body


class TestBitLiberaService:
    def test_request_onramp_otp_payload(self):
        service = BitLiberaService(_FakeBitLiberaClient({"success": True}))
        service.request_onramp_otp("+2571", Decimal("1000.50"))
        endpoint, data = service.client.last_call
        assert endpoint == endpoints.ONRAMP_REQUEST_OTP
        assert data == {"phone": "+2571", "amount": 1000}

    def test_execute_onramp_payload(self):
        service = BitLiberaService(_FakeBitLiberaClient({"success": True}))
        service.execute_onramp("+2571", Decimal("5000"), "123456", "order-1")
        endpoint, data = service.client.last_call
        assert endpoint == endpoints.ONRAMP_EXECUTE
        assert data == {"phone": "+2571", "amount": 5000, "otp": "123456", "order_id": "order-1"}

    def test_create_offramp_invoice_payload(self):
        service = BitLiberaService(
            _FakeBitLiberaClient({"success": True, "payment_request": "lnbc1"})
        )
        body = service.create_offramp_invoice("+2571", Decimal("25000"), "order-1")
        endpoint, data = service.client.last_call
        assert endpoint == endpoints.OFFRAMP_CREATE_INVOICE
        assert data == {
            "recipient_phone": "+2571",
            "amount_bif": 25000,
            "order_id": "order-1",
        }
        assert body["payment_request"] == "lnbc1"

    def test_order_status_polls_and_translates(self):
        service = BitLiberaService(_FakeBitLiberaClient({"status": "SETTLED"}))
        assert service.order_status("order-1") == "paid"
        endpoint, _ = service.client.last_call
        assert endpoint == endpoints.ORDER_STATUS.format(order_id="order-1")


class TestBitLiberaPaymentFlow:
    """On-ramp then off-ramp cycle, mirroring the Node reference's routes."""

    def _service(self) -> tuple[BitLiberaService, FakeSession]:
        session = FakeSession(
            [
                FakeResponse({"success": True, "otp_status": "SENT"}),
                FakeResponse({"success": True, "order_id": "org-1", "status": "PENDING_PAYMENT"}),
                FakeResponse(
                    {
                        "success": True,
                        "order_id": "off-1",
                        "payment_request": "lnbc1",
                        "payment_hash": "h1",
                        "amount_sats": 12345,
                    }
                ),
                FakeResponse({"success": True, "status": "SETTLED"}),
            ]
        )
        client = BitLiberaClient(
            base_url="https://exchanger.bitlibera.com",
            api_key="bl_live_1",
            session=session,
        )
        return BitLiberaService(client), session

    def test_onramp_and_offramp(self):
        service, session = self._service()

        otp = service.request_onramp_otp("+25770000001", Decimal("10000"))
        assert otp["success"] is True

        onramp = service.execute_onramp("+25770000001", Decimal("10000"), "123456", "org-1")
        assert onramp["order_id"] == "org-1"

        invoice = service.create_offramp_invoice("+25770000001", Decimal("10000"), "off-1")
        assert invoice["payment_request"] == "lnbc1"

        assert service.order_status("off-1") == "paid"

        assert len(session.calls) == 4
        for url, kwargs in session.calls:
            assert kwargs["headers"]["x-api-key"] == "bl_live_1"
        assert session.calls[0][0].endswith(endpoints.ONRAMP_REQUEST_OTP)
