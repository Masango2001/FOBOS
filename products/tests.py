"""Product CRUD + barcode endpoints (Tech Spec §4, §8 step 3)."""

import pytest


@pytest.fixture
def payload(business):
    return {
        "name": "Juice",
        "barcode": "8899",
        "unit_cost": "80.00",
        "unit_price": "200.00",
        "stock_qty": 20,
        "stock_threshold": 4,
    }


@pytest.mark.django_db
class TestProductCreate:
    def test_owner_can_create_product(self, owner_client, payload, business):
        response = owner_client.post("/products", payload, format="json")

        assert response.status_code == 201
        assert response.json()["name"] == "Juice"
        assert business.products.count() == 1

    def test_product_isolated_per_business(self, owner_client, payload, business, db):
        from accounts.models import Business

        other = Business.objects.create(name="Other", owner=business.owner)
        owner_client.post("/products", payload, format="json")
        assert business.products.count() == 1
        assert other.products.count() == 0

    def test_cashier_cannot_create_product(self, cashier_client, payload):
        response = cashier_client.post("/products", payload, format="json")
        assert response.status_code == 403

    def test_barcode_can_be_blank(self, owner_client, business):
        payload = {
            "name": "No barcode",
            "unit_cost": "10.00",
            "unit_price": "30.00",
            "stock_qty": 1,
            "stock_threshold": 0,
        }
        response = owner_client.post("/products", payload, format="json")
        assert response.status_code == 201

    def test_duplicate_barcode_rejected(self, owner_client, payload, product, business):
        payload["barcode"] = product.barcode
        response = owner_client.post("/products", payload, format="json")
        assert response.status_code == 400  # uniq_business_barcode


@pytest.mark.django_db
class TestProductRead:
    def test_list_products(self, owner_client, product):
        response = owner_client.get("/products")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["stock_qty"] == 10

    def test_scan_by_barcode(self, owner_client, product):
        response = owner_client.get("/products/scan/6161")
        assert response.status_code == 200
        assert response.json()["id"] == product.id

    def test_scan_unknown_barcode(self, owner_client):
        response = owner_client.get("/products/scan/9999")
        assert response.status_code == 404

    def test_cashier_can_scan_to_build_cart(self, cashier_client, product):
        response = cashier_client.get("/products/scan/6161")
        assert response.status_code == 200
