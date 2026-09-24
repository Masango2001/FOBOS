from rest_framework import serializers

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "barcode",
            "unit_cost",
            "unit_price",
            "stock_qty",
            "stock_threshold",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

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
