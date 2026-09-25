from rest_framework import serializers

from ledger.models import CURRENCIES


class CheckoutSerializer(serializers.Serializer):
    """POST /cart/checkout payload — lines (product cart) or a custom amount (§4)."""

    lines = serializers.ListField(child=serializers.DictField(), required=False, allow_empty=False)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    currency = serializers.ChoiceField(choices=CURRENCIES, default="BIF")
