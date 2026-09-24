"""OpenAPI schema smoke test (drf-spectacular)."""

import pytest


def _get_schema():
    from drf_spectacular.views import SpectacularAPIView
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().get("/api/schema/")
    response = SpectacularAPIView.as_view()(request)
    assert response.status_code == 200
    return response.data


@pytest.mark.django_db
class TestOpenApi:
    def test_schema_generates(self):
        from drf_spectacular.validation import validate_schema

        validate_schema(_get_schema())

    def test_schema_exposes_stock_movement_endpoints(self):
        paths = _get_schema()["paths"]
        assert "/inventory/movements" in paths
        assert "/inventory/adjustments" in paths
        assert "/inventory/restock" in paths

    def test_api_view_operations_have_typed_success_responses(self):
        schema = _get_schema()
        expected = {
            ("/auth/resend-verification", "post", "200", "application/json"),
            ("/auth/verify-email/{token}/", "get", "200", "text/html"),
            ("/auth/verify-email/{token}/", "get", "400", "text/html"),
            ("/auth/verify-email/{token}/", "get", "404", "text/html"),
            ("/automations/executions", "get", "200", "application/json"),
            ("/cart/checkout", "post", "201", "application/json"),
            ("/dashboard", "get", "200", "application/json"),
            ("/inventory", "get", "200", "application/json"),
            ("/inventory/adjustments", "post", "201", "application/json"),
            ("/inventory/movements", "get", "200", "application/json"),
            ("/inventory/restock", "post", "201", "application/json"),
            ("/ledger", "get", "200", "application/json"),
            ("/payments/{id}/status", "get", "200", "application/json"),
            ("/payments/onramp/confirm", "post", "200", "application/json"),
            ("/payments/onramp/request-otp", "post", "200", "application/json"),
            ("/products/scan/{barcode}", "get", "200", "application/json"),
        }

        for path, method, status_code, content_type in expected:
            response = schema["paths"][path][method]["responses"][status_code]
            assert content_type in response["content"], (path, method, status_code)
            assert "schema" in response["content"][content_type], (path, method, status_code)

    def test_stock_movement_query_and_mutation_contracts(self):
        paths = _get_schema()["paths"]

        movement_list = paths["/inventory/movements"]["get"]
        assert {"product_id", "type", "limit", "cursor"}.issubset(
            {parameter["name"] for parameter in movement_list["parameters"]}
        )
        limit_parameter = next(
            parameter for parameter in movement_list["parameters"] if parameter["name"] == "limit"
        )
        assert limit_parameter["schema"]["minimum"] == 1
        assert limit_parameter["schema"]["maximum"] == 200
        assert limit_parameter["schema"]["default"] == 50

        for path in ("/inventory/adjustments", "/inventory/restock"):
            operation = paths[path]["post"]
            assert "201" in operation["responses"]
            assert "409" in operation["responses"]
            assert "200" not in operation["responses"]
            response_schema = operation["responses"]["201"]["content"]["application/json"]["schema"]
            assert response_schema["$ref"].endswith("/StockMutationResponse")

    def test_checkout_and_payment_requests_are_documented(self):
        paths = _get_schema()["paths"]

        for path in (
            "/auth/resend-verification",
            "/cart/checkout",
            "/inventory/adjustments",
            "/inventory/restock",
            "/payments/onramp/confirm",
            "/payments/onramp/request-otp",
        ):
            assert "application/json" in paths[path]["post"]["requestBody"]["content"]
