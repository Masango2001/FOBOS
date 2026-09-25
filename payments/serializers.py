"""Payment API serializers — shapes agreed with the Frontend (cashier contract).

Canonical status enum returned to clients: pending | paid | failed | expired |
cancelled (adapter/provider states like PENDING_PAYMENT are internal to the payment
rail adapters). purpose distinguishes checkout vs subscription (doc §40–41).
"""

from rest_framework import serializers

from .models import Payment

RECEIPT_FIELDS = ["id", "content", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    receipt = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "order_id",
            "payment_request",
            "amount_bif",
            "amount_sats",
            "currency",
            "settlement_currency",
            "purpose",
            "rail",
            "lumicash_phone",
            "status",
            "confirmed_at",
            "receipt",
        ]
        read_only_fields = fields

    def get_receipt(self, obj: Payment):
        if obj.financial_event_id is None:
            return None
        from sales.models import Receipt

        receipt = Receipt.objects.filter(sale__financial_event=obj.financial_event_id).first()
        if receipt is None:
            return None
        return {"id": receipt.id, "content": receipt.content, "created_at": receipt.created_at}


class OnrampRequestSerializer(serializers.Serializer):
    """POST /payments/onramp/request-otp — Lumicash OTP (Tech Spec §4)."""

    customer_phone = serializers.CharField(max_length=30)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)


class OnrampConfirmSerializer(serializers.Serializer):
    """POST /payments/onramp/confirm — executes the OTP against an order (Tech Spec §4)."""

    customer_phone = serializers.CharField(max_length=30)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    otp = serializers.CharField(max_length=10)
    order_id = serializers.CharField(max_length=64)
