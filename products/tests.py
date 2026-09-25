"""Product CRUD + barcode endpoints (Tech Spec §4, §8 step 3)."""

from pathlib import Path

import pytest

from products.services import calculate_ean13_check_digit, parse_product_barcode


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

    def test_blank_barcode_generates_internal_ean13(self, owner_client, business):
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
        assert len(barcode) == 13
        assert barcode.startswith("20")
        assert barcode[-1] == calculate_ean13_check_digit(barcode[:12])
        assert business.products.get(id=response.json()["id"]).barcode == barcode
        scanned = owner_client.get(f"/products/scan/{barcode}")
        assert scanned.status_code == 200
        assert scanned.json()["id"] == response.json()["id"]

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
class TestProductDetail:
    def test_owner_can_get_product(self, owner_client, product):
        response = owner_client.get(f"/products/{product.id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(product.id)

    def test_cashier_can_read_but_not_write(self, cashier_client, product):
        assert cashier_client.get(f"/products/{product.id}").status_code == 200
        patch = cashier_client.patch(f"/products/{product.id}", {"name": "Hack"}, format="json")
        assert patch.status_code == 403
        assert cashier_client.delete(f"/products/{product.id}").status_code == 403

    def test_cross_business_get_returns_404(self, owner_client, product):
        from accounts.models import Business, User
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import AccessToken

        other_owner = User.objects.create_user(
            email="other@fobos.test", name="Other", password="supersecret123", role="owner"
        )
        other = Business.objects.create(name="Other", owner=other_owner)
        other_owner.business = other
        other_owner.save(update_fields=["business"])

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(other_owner)}")
        assert client.get(f"/products/{product.id}").status_code == 404

    def test_owner_can_patch_product(self, owner_client, product):
        response = owner_client.patch(
            f"/products/{product.id}", {"unit_price": "300.00"}, format="json"
        )
        assert response.status_code == 200
        product.refresh_from_db()
        assert product.unit_price == 300

    def test_owner_can_delete_product(self, owner_client, business):
        product = business.products.create(name="Temp", barcode="7777", unit_price=10)
        assert owner_client.delete(f"/products/{product.id}").status_code == 204

    def test_delete_product_with_movements_conflicts(self, owner_client, product):
        from products.models import StockMovement

        StockMovement.objects.create(
            business=product.business,
            product=product,
            type=StockMovement.MovementType.RESTOCK,
            qty_delta=10,
            qty_after=10,
        )
        assert owner_client.delete(f"/products/{product.id}").status_code == 409

    def test_duplicate_barcode_on_update_rejected(self, owner_client, product, business):
        business.products.create(name="Other", barcode="9999", unit_price=5)
        response = owner_client.patch(f"/products/{product.id}", {"barcode": "9999"}, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestProductUpdateRegeneratesBarcode:
    def test_update_price_regenerates_fobos_barcode(self, owner_client, business):
        payload = {"name": "Sap", "unit_cost": "50.00", "unit_price": "150.00", "stock_qty": 0}
        created = owner_client.post("/products", payload, format="json").json()
        first = created["barcode"]
        assert first.startswith("F.")

        response = owner_client.patch(
            f"/products/{created['id']}", {"unit_price": "175.00"}, format="json"
        )
        assert response.status_code == 200
        refreshed = response.json()["barcode"]
        assert refreshed != first
        assert parse_product_barcode(refreshed).price == "175.00"

    def test_update_name_regenerates_fobos_barcode(self, owner_client, product):
        # Product created WITHOUT a barcode gets a FOBOS-generated one; renaming
        # it must re-encode the new name into the code.
        created = owner_client.post(
            "/products",
            {"name": "Sap", "unit_cost": "50.00", "unit_price": "150.00", "stock_qty": 0},
            format="json",
        ).json()
        assert created["barcode"].startswith("F.")

        response = owner_client.patch(
            f"/products/{created['id']}", {"name": "Renamed Soda"}, format="json"
        )
        assert response.status_code == 200
        refreshed = response.json()["barcode"]
        assert refreshed != created["barcode"]
        assert parse_product_barcode(refreshed).name == "Renamed Soda"

    def test_update_manufacturer_barcode_is_never_overwritten(self, owner_client, product):
        response = owner_client.patch(
            f"/products/{product.id}", {"unit_price": "300.00"}, format="json"
        )
        assert response.status_code == 200
        product.refresh_from_db()
        assert product.barcode == "6161"  # manufacturer value kept, not regenerated

    def test_creating_product_persists_png_and_returns_url(self, owner_client, owner):
        response = owner_client.post(
            "/products",
            {"name": "Juice", "unit_cost": "80.00", "unit_price": "200.00", "stock_qty": 20},
            format="json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["barcode_image_url"].startswith("http://testserver/media/barcodes/")
        assert body["barcode_image_url"].endswith(".png")

        from pathlib import Path

        from django.conf import settings

        product = owner.business.products.get(id=body["id"])
        assert product.barcode_image.name == f"barcodes/{product.id}.png"
        path = (Path(settings.MEDIA_ROOT) / "barcodes" / f"{product.id}.png").resolve()
        assert path.exists()
        assert path.read_bytes().startswith(b"\x89PNG")

    def test_barcode_image_url_works_for_cashier(self, cashier_client, product):
        response = cashier_client.get("/products")
        assert response.status_code == 200
        item = next(p for p in response.json() if p["id"] == str(product.id))
        assert item["barcode_image_url"].startswith("http://testserver/media/barcodes/")

    def test_changing_barcode_regenerates_same_file(self, business):
        from products.models import Product

        p = Product.objects.create(business=business, name="R", barcode="111", unit_price=10)
        assert p.barcode_image.name == f"barcodes/{p.id}.png"

        first = p.barcode_image.read()
        p.barcode = "222"
        p.save(update_fields=["barcode"])

        p.refresh_from_db()
        assert p.barcode_image.name == f"barcodes/{p.id}.png"  # same path — no orphan
        assert p.barcode_image.read() != first

    def test_clearing_barcode_removes_image(self, business):
        from django.conf import settings

        from products.models import Product

        p = Product.objects.create(business=business, name="R", barcode="111", unit_price=10)
        path = (Path(settings.MEDIA_ROOT) / p.barcode_image.name).resolve()
        assert path.exists()

        p.barcode = None
        p.save(update_fields=["barcode"])
        p.refresh_from_db()
        assert p.barcode_image.name in ("", None)  # ImageField → empty is None
        assert not path.exists()

    def test_no_image_when_barcode_missing(self, business):
        from products.models import Product

        p = Product.objects.create(business=business, name="No bar", barcode=None, unit_price=10)
        assert p.barcode_image.name in ("", None)  # empty ImageField → None
