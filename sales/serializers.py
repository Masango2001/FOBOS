from rest_framework import serializers
from decimal import Decimal

from .models import Receipt, Sale, SaleLine


class CheckoutSerializer(serializers.Serializer):
    """POST /cart/checkout payload — lines (product cart) or a custom amount (§4)."""

    lines = serializers.ListField(child=serializers.DictField(), required=False, allow_empty=False)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    currency = serializers.ChoiceField(
        choices=[("BIF", "BIF"), ("USD", "USD"), ("SAT", "SAT")], default="BIF"
    )
    payment_method = serializers.ChoiceField(
        choices=[("qr", "QR invoice"), ("lumicash_otp", "Lumicash OTP"), ("cash", "Cash")],
        default="qr",
    )
    customer_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    amount_tendered = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)


class SaleLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    line_cogs = serializers.SerializerMethodField()
    line_gross_profit = serializers.SerializerMethodField()

    class Meta:
        model = SaleLine
        fields = ["id", "product_id", "product_name", "quantity", "unit_price", "unit_cost", "line_cogs", "line_gross_profit"]

    def get_line_cogs(self, obj) -> Decimal:
        return obj.unit_cost * obj.quantity

    def get_line_gross_profit(self, obj) -> Decimal:
        return (obj.unit_price - obj.unit_cost) * obj.quantity


class SaleSerializer(serializers.ModelSerializer):
    cashier_name = serializers.CharField(source="cashier.name", read_only=True, allow_null=True)
    lines = SaleLineSerializer(source="sale_lines", many=True, read_only=True)
    order_id = serializers.CharField(source="financial_event.reference", read_only=True)
    receipt_number = serializers.SerializerMethodField()
    payment_rail = serializers.CharField(source="financial_event.source", read_only=True)
    payment_reference = serializers.CharField(source="financial_event.reference", read_only=True)
    tax_amount = serializers.SerializerMethodField()
    gross_profit = serializers.SerializerMethodField()
    gross_margin_percent = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = ["id", "business_id", "financial_event_id", "order_id", "cashier_id", "cashier_name", "receipt_number", "total_amount", "tax_amount", "gross_profit", "gross_margin_percent", "currency", "payment_rail", "payment_reference", "lines", "created_at"]

    def get_receipt_number(self, obj) -> str:
        receipt = getattr(obj, "receipt", None)
        return str(receipt.id) if receipt else str(obj.id)

    def get_tax_amount(self, obj) -> Decimal:
        return (obj.total_amount * Decimal("18") / Decimal("118")).quantize(Decimal("0.01"))

    def get_gross_profit(self, obj) -> Decimal:
        cogs = sum((line.unit_cost * line.quantity for line in obj.sale_lines.all()), Decimal("0"))
        return obj.total_amount - cogs

    def get_gross_margin_percent(self, obj) -> float:
        profit = self.get_gross_profit(obj)
        return round(float(profit / obj.total_amount * 100), 1) if obj.total_amount else 0


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = ["id", "content", "created_at"]
