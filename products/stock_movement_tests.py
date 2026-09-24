"""LOT 1 stock movements — append-only ledger, adjustments, and sale integration.

Covers the six business rules:
  1. every confirmed sale → one "sale" movement per cart line, same transaction
  2. stock can never go negative → 409
  3. stock never changes without an associated movement
  4. idempotency on order_id (no duplicate movement/ledger on retry)
  5. /inventory is always consistent with sum(qty_delta)
  6. adjustments require a non-empty reason
"""

import uuid

import pytest

from products.models import StockMovement


def _confirm(order_id: str, amount_bif: int = 250, actor: str = "alice@fobos.test"):
    from payments.services import confirm_payment

    return confirm_payment(order_id=order_id, amount_bif=amount_bif, actor=actor)


def _checkout(client, product, qty: int = 1):
    response = client.post(
        "/cart/checkout",
        {"lines": [{"product_id": product.id, "quantity": qty}]},
        format="json",
    )
    return response.json()["order_id"]


def _adjust(client, product, delta, reason="casse"):
    return client.post(
        "/inventory/adjustments",
        {"product_id": product.id, "qty_delta": delta, "reason": reason},
        format="json",
    )


def _restock(client, product, quantity, reason="livraison"):
    return client.post(
        "/inventory/restock",
        {"product_id": product.id, "quantity": quantity, "reason": reason},
        format="json",
    )


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
class TestInitialStock:
    def test_creating_product_records_initial_restock_movement(self, owner_client, payload):
        response = owner_client.post("/products", payload, format="json")
        assert response.status_code == 201

        movement = StockMovement.objects.get(
            product_id=response.json()["id"],
            type=StockMovement.MovementType.RESTOCK,
        )
        assert movement.qty_delta == 20
        assert movement.qty_after == 20
        assert movement.reason == "stock initial"

    def test_orm_created_product_gets_initial_movement(self, product):
        """Rule 5 must hold even when products enter via the ORM (fixtures/data)."""
        movement = StockMovement.objects.get(
            product=product, type=StockMovement.MovementType.RESTOCK
        )
        assert movement.qty_delta == 10
        assert movement.qty_after == 10

    def test_zero_stock_product_has_no_initial_movement(self, business):
        from products.models import Product

        p = Product.objects.create(business=business, name="Zero", unit_price=5, stock_qty=0)
        assert p.stock_movements.count() == 0


@pytest.mark.django_db
class TestMovementList:
    def test_cashier_can_read_movements(self, cashier_client, product):
        product.refresh_from_db()  # fixture creation fires the restock signal
        response = cashier_client.get("/inventory/movements")
        assert response.status_code == 200
        body = response.json()
        assert body["next_cursor"] is None
        assert len(body["items"]) == 1
        assert body["items"][0]["type"] == "restock"

    def test_lists_movements_for_business(self, owner_client, product):
        product.refresh_from_db()  # fixture creation fires the restock signal
        response = owner_client.get("/inventory/movements")
        assert response.status_code == 200
        body = response.json()
        assert body["next_cursor"] is None
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["type"] == "restock"
        assert item["qty_delta"] == 10
        assert item["qty_after"] == 10
        assert item["product_id"] == str(product.id)
        assert item["reference"] is None
        assert item["reason"] == "stock initial"

    def test_filters_by_product_and_type(self, owner_client, product, business):
        from products.models import Product

        other = Product.objects.create(business=business, name="Other", unit_price=5, stock_qty=3)
        response = owner_client.get(f"/inventory/movements?product_id={other.id}&type=restock")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["product_id"] == str(other.id)

    def test_invalid_type_rejected(self, owner_client):
        response = owner_client.get("/inventory/movements?type=giveaway")
        assert response.status_code == 400

    def test_invalid_limit_rejected(self, owner_client):
        response = owner_client.get("/inventory/movements?limit=10000")
        assert response.status_code == 400

    def test_cursor_pagination(self, owner_client, business):
        from products.models import Product

        product = Product.objects.create(business=business, name="Page", unit_price=5, stock_qty=60)
        for delta in (10, 20, 30, 40, 50, 60):
            StockMovement.objects.create(
                business=business,
                product=product,
                type=StockMovement.MovementType.ADJUSTMENT,
                qty_delta=delta,
                qty_after=delta,
                reason="casse",
            )

        first = owner_client.get("/inventory/movements?limit=3").json()
        assert len(first["items"]) == 3
        assert first["next_cursor"] is not None

        second = owner_client.get(
            f"/inventory/movements?limit=3&cursor={first['next_cursor']}"
        ).json()
        assert len(second["items"]) == 3
        # Keyset pagination: no overlap between pages, all different.
        first_ids = {i["id"] for i in first["items"]}
        second_ids = {i["id"] for i in second["items"]}
        assert first_ids.isdisjoint(second_ids)
        assert second["next_cursor"] is not None

        third = owner_client.get(
            f"/inventory/movements?limit=3&cursor={second['next_cursor']}"
        ).json()
        assert len(third["items"]) == 1
        assert third["next_cursor"] is None

    def test_invalid_cursor_rejected(self, owner_client):
        response = owner_client.get("/inventory/movements?cursor=not-a-cursor")
        assert response.status_code == 400


@pytest.mark.django_db
class TestAdjustments:
    def test_owner_can_apply_adjustment(self, owner_client, product):
        product.refresh_from_db()
        response = _adjust(owner_client, product, -3, reason="casse")

        assert response.status_code == 201
        body = response.json()
        assert body["movement"]["type"] == "adjustment"
        assert body["movement"]["qty_delta"] == -3
        assert body["movement"]["qty_after"] == 7
        assert body["movement"]["reason"] == "casse"
        assert body["product"]["stock_qty"] == 7

        product.refresh_from_db()
        assert product.stock_qty == 7

    def test_adjustment_records_positive_delta(self, owner_client, product):
        response = _adjust(owner_client, product, 5, reason="casse")
        assert response.status_code == 201
        assert response.json()["product"]["stock_qty"] == 15
        assert response.json()["movement"]["qty_after"] == 15

    def test_cashier_blocked_from_adjustments(self, cashier_client, product):
        response = _adjust(cashier_client, product, 1)
        assert response.status_code == 403

    def test_negative_stock_rejected_with_409(self, owner_client, product):
        response = _adjust(owner_client, product, -99)
        assert response.status_code == 409
        assert response.json()["code"] == "negative_stock"

        product.refresh_from_db()
        assert product.stock_qty == 10
        assert product.stock_movements.filter(type="adjustment").count() == 0

    def test_unknown_product_rejected(self, owner_client):
        response = owner_client.post(
            "/inventory/adjustments",
            {"product_id": str(uuid.uuid4()), "qty_delta": 1, "reason": "casse"},
            format="json",
        )
        assert response.status_code in (400, 404)

    def test_reason_required(self, owner_client, product):
        response = _adjust(owner_client, product, -1, reason="")
        assert response.status_code == 400
        assert "reason" in response.json()


@pytest.mark.django_db
class TestRestockEndpoint:
    def test_restock_adds_stock_and_records_movement(self, owner_client, product):
        response = _restock(owner_client, product, 10)
        assert response.status_code == 201
        data = response.json()

        product.refresh_from_db()
        assert product.stock_qty == 20
        assert data["product"]["stock_qty"] == 20
        assert data["movement"]["type"] == "restock"
        assert data["movement"]["qty_delta"] == 10
        assert data["movement"]["qty_after"] == 20
        assert data["movement"]["reason"] == "livraison"

    def test_restock_requires_positive_quantity(self, owner_client, product):
        response = _restock(owner_client, product, 0)
        assert response.status_code == 400
        assert "quantity" in response.json()

        response = _restock(owner_client, product, -5)
        assert response.status_code == 400
        assert "quantity" in response.json()

        product.refresh_from_db()
        assert product.stock_qty == 10
        assert product.stock_movements.filter(type="restock").count() == 1

    def test_cashier_blocked_from_restock(self, cashier_client, product):
        response = _restock(cashier_client, product, 5)
        assert response.status_code == 403

    def test_restock_unknown_product_rejected(self, owner_client):
        response = owner_client.post(
            "/inventory/restock",
            {"product_id": str(uuid.uuid4()), "quantity": 5, "reason": "livraison"},
            format="json",
        )
        assert response.status_code in (400, 404)

    def test_restock_requires_reason(self, owner_client, product):
        response = _restock(owner_client, product, 5, reason="")
        assert response.status_code == 400
        assert "reason" in response.json()


@pytest.mark.django_db
class TestSaleMovementsAtCheckout:
    def test_confirm_creates_sale_movement_per_line(self, owner_client, product):
        order_id = _checkout(owner_client, product, qty=2)
        _confirm(order_id)

        sale_movement = StockMovement.objects.get(
            product=product, type=StockMovement.MovementType.SALE
        )
        assert sale_movement.qty_delta == -2
        assert sale_movement.qty_after == 8
        assert sale_movement.reference == order_id  # rule 4: idempotency key
        assert sale_movement.reason == "vente"

        product.refresh_from_db()
        assert product.stock_qty == 8

    def test_multi_line_cart_creates_one_movement_per_product(self, owner_client, business):
        from products.models import Product

        soda = Product.objects.create(business=business, name="Soda", unit_price=250, stock_qty=10)
        juice = Product.objects.create(business=business, name="Juice", unit_price=200, stock_qty=5)
        response = owner_client.post(
            "/cart/checkout",
            {
                "lines": [
                    {"product_id": soda.id, "quantity": 2},
                    {"product_id": juice.id, "quantity": 1},
                ]
            },
            format="json",
        )
        assert response.status_code == 201
        _confirm(response.json()["order_id"])

        assert StockMovement.objects.filter(type="sale").count() == 2
        soda.refresh_from_db()
        juice.refresh_from_db()
        assert (soda.stock_qty, juice.stock_qty) == (8, 4)

    def test_duplicate_confirmation_does_not_duplicate_movements(self, owner_client, product):
        """Rule 4: a retried confirmation must not create a second sale movement."""
        order_id = _checkout(owner_client, product)
        _confirm(order_id)
        _confirm(order_id)  # duplicate → idempotent
        _confirm(order_id)

        assert (
            StockMovement.objects.filter(product=product, type="sale", reference=order_id).count()
            == 1
        )
        product.refresh_from_db()
        assert product.stock_qty == 9

    def test_failed_confirmation_rolls_back_movement(self, owner_client, product):
        """Rule 3 + PRD §27: no partial state — a failed confirm creates no movement."""
        order_id = _checkout(owner_client, product)

        product.stock_qty = 0
        product.save(update_fields=["stock_qty"])

        from sales.services import InsufficientStockError

        with pytest.raises(InsufficientStockError):
            _confirm(order_id)

        assert StockMovement.objects.filter(type="sale").count() == 0
        product.refresh_from_db()
        assert product.stock_qty == 0


@pytest.mark.django_db
class TestInventoryConsistency:
    def test_inventory_equals_sum_of_qty_delta(self, owner_client, product):
        """Rule 5: after sales + adjustments, stock_qty == sum(qty_delta)."""
        _adjust(owner_client, product, 5, reason="restock manuel")
        order_id = _checkout(owner_client, product, qty=2)
        _confirm(order_id)

        total_delta = sum(m.qty_delta for m in product.stock_movements.all())
        product.refresh_from_db()
        assert total_delta == product.stock_qty

    def test_inventory_endpoint_matches_stock(self, owner_client, business):
        from products.models import Product

        p = Product.objects.create(business=business, name="X", unit_price=9, stock_qty=7)
        _adjust(owner_client, p, 2, reason="retour fournisseur")

        response = owner_client.get("/inventory")
        assert response.status_code == 200
        item = next(i for i in response.json() if i["id"] == str(p.id))
        assert item["stock_qty"] == 9
        assert item["stock_qty"] == sum(m.qty_delta for m in p.stock_movements.all())
