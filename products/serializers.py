from rest_framework import serializers

from .models import Product, StockMovement


class ProductSerializer(serializers.ModelSerializer):
    """barcode_image = absolute URL of the persisted Code128 PNG (local media volume)."""

    barcode_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "barcode",
            "barcode_image_url",
            "unit_cost",
            "unit_price",
            "stock_qty",
            "stock_threshold",
            "created_at",
        ]
        read_only_fields = ["id", "barcode_image_url", "created_at"]

    def get_barcode_image_url(self, obj) -> str | None:
        if not obj.barcode_image:
            return None
        request = self.context.get("request")
        url = obj.barcode_image.url
        return request.build_absolute_uri(url) if request is not None else url

    def validate_barcode(self, value: str | None) -> str | None:
        if value in ("", None):
            return None
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs.get("unit_price", 0) < 0:
            raise serializers.ValidationError({"unit_price": "Must be >= 0."})
        if attrs.get("unit_cost", 0) < 0:
            raise serializers.ValidationError({"unit_cost": "Must be >= 0."})
        return attrs


class StockMovementSerializer(serializers.ModelSerializer):
    """Read representation of one append-only stock movement (LOT 1)."""

    type = serializers.ChoiceField(choices=StockMovement.MovementType.choices)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product_id",
            "type",
            "qty_delta",
            "qty_after",
            "reference",
            "reason",
            "created_at",
        ]
        read_only_fields = fields


class StockAdjustmentSerializer(serializers.Serializer):
    """POST /inventory/adjustments body (LOT 1)."""

    product_id = serializers.UUIDField()
    qty_delta = serializers.IntegerField()
    reason = serializers.CharField(
        max_length=255, allow_blank=False, trim_whitespace=True, required=True
    )


class StockRestockSerializer(serializers.Serializer):
    """POST /inventory/restock body — restock a product (owner only)."""

    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(
        max_length=255, allow_blank=False, trim_whitespace=True, required=True
    )
