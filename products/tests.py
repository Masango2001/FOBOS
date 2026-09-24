"""Product CRUD + barcode endpoints (Tech Spec §4, §8 step 3)."""

import pytest

from products.services import parse_product_barcode


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

    def test_barcode_can_be_blank_auto_generates_fobos_barcode(self, owner_client, business):
        payload = {
            "name": "No barcode",
            "unit_cost": "10.00",
            "unit_price": "30.00",
            "stock_qty": 1,
            "stock_threshold": 0,
        }
        response = owner_client.post("/products", payload, format="json")

        assert response.status_code == 201
        barcode = response.json()["barcode"]
        assert barcode.startswith("F.")
        decoded = parse_product_barcode(barcode)
        assert decoded is not None
        assert decoded.name == "No barcode"
        assert decoded.price == "30.00"
        assert decoded.product_id == response.json()["id"]

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
        assert response.json()["id"] == str(product.id)

    def test_scan_fobos_barcode_resolves_by_embedded_id(self, owner_client, product):
        from decimal import Decimal

        from products.services import build_product_barcode

        barcode = build_product_barcode(
            name=product.name, price=Decimal("250.00"), product_id=product.id
        )
        response = owner_client.get(f"/products/scan/{barcode}")
        assert response.status_code == 200
        assert response.json()["id"] == str(product.id)

    def test_scan_unknown_barcode(self, owner_client):
        response = owner_client.get("/products/scan/9999")
        assert response.status_code == 404

    def test_cashier_can_scan_to_build_cart(self, cashier_client, product):
        response = cashier_client.get("/products/scan/6161")
        assert response.status_code == 200


@pytest.mark.django_db
class TestBarcodeImage:
    def test_barcode_image_returns_png(self, owner_client, product):
        response = owner_client.get(f"/products/{product.id}/barcode")

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")
        assert response["Cache-Control"] == "public, max-age=31536000, immutable"

    def test_barcode_image_works_for_cashier(self, cashier_client, product):
        response = cashier_client.get(f"/products/{product.id}/barcode")
        assert response.status_code == 200

    def test_barcode_image_404_for_other_business(self, owner_client, business):
        from accounts.models import Business

        other = Business.objects.create(name="Other", owner=business.owner)
        from products.models import Product

        other_product = Product.objects.create(
            business=other, name="Other item", barcode="1234", unit_price=10
        )
        response = owner_client.get(f"/products/{other_product.id}/barcode")
        assert response.status_code == 404

    def test_barcode_image_404_when_no_barcode(self, owner_client, business):
        from products.models import Product

        blank = Product.objects.create(
            business=business, name="No bar", barcode=None, unit_price=10
        )
        response = owner_client.get(f"/products/{blank.id}/barcode")
        assert response.status_code == 404
