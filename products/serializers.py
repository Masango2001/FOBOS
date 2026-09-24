from rest_framework import serializers

from .models import Product


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
