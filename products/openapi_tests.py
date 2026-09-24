"""OpenAPI schema smoke test (drf-spectacular)."""

import pytest


@pytest.mark.django_db
class TestOpenApi:
    def test_schema_generates(self):
        from drf_spectacular.validation import validate_schema
        from drf_spectacular.views import SpectacularAPIView
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get("/api/schema/")
        response = SpectacularAPIView.as_view()(request)
        assert response.status_code == 200
        validate_schema(response.data)

    def test_schema_exposes_stock_movement_endpoints(self):
        from drf_spectacular.views import SpectacularAPIView
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get("/api/schema/")
        response = SpectacularAPIView.as_view()(request)
        paths = response.data["paths"]
        assert "/inventory/movements" in paths
        assert "/inventory/adjustments" in paths
        assert "/inventory/restock" in paths
