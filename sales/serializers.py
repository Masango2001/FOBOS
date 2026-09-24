from rest_framework import serializers


class CheckoutSerializer(serializers.Serializer):
    """POST /cart/checkout payload — lines (product cart) or a custom amount (§4)."""

    lines = serializers.ListField(child=serializers.DictField(), required=False, allow_empty=False)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    currency = serializers.ChoiceField(
        choices=[("BIF", "BIF"), ("USD", "USD"), ("SAT", "SAT")], default="BIF"
    )
