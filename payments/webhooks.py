"""Blink rail webhook (Tech Spec §27–28) — rail → FOBOS order confirmation.

Backend Dev B's real Blink adapter POSTs here (canonical payload with an
`order_id`) when a merchant order is paid; because `confirm_payment` is
idempotent on `order_id` and guarded by `select_for_update`, retries from the
rail can never double-confirm: the first call creates the FinancialEvent, every
later one returns the same event.

The official Blink signature check (doc §28) is left to Backend Dev B to wire
once the real adapter lands; this handler only does contract validation.
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Payment
from .services import confirm_payment


@csrf_exempt
@api_view(["POST"])
def blink_webhook(request) -> Response:
    """POST /payments/webhooks/blink — rail reports an order as paid.

    Accepts both the canonical envelope (`{"order_id": "...", "status": ...}`)
    and the flat form (`order_id` at top level). Failure/expiry are answered with
    200 so the rail stops retrying; only a paid/confirmed/settled state calls
    `confirm_payment`.
    """
    data = getattr(request.data, "data", request.data)
    try:
        payload = data if isinstance(data, dict) else {}
        order_id = payload.get("order_id") or payload.get("orderId")
        rail_status = (payload.get("status") or "").lower()
    except AttributeError:
        return Response({"detail": "Malformed Blink payload."}, status=status.HTTP_400_BAD_REQUEST)

    if not isinstance(order_id, str) or not order_id:
        return Response(
            {"code": "missing_order_id", "detail": "Need a string 'order_id'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if rail_status in ("paid", "confirmed", "settled"):
        confirmed_at = payload.get("confirmed_at") or None
        try:
            event = confirm_payment(
                order_id=order_id,
                actor="blink_webhook",
                confirmed_at=confirmed_at or None,
            )
        except Payment.DoesNotExist:
            return Response(
                {"code": "unknown_order", "detail": f"No payment for {order_id}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {"order_id": order_id, "status": "paid", "event_id": str(event.id)},
            status=status.HTTP_200_OK,
        )

    # Failed/expired/cancelled — acknowledge so the rail stops retrying.
    return Response({"order_id": order_id, "status": rail_status}, status=status.HTTP_200_OK)
