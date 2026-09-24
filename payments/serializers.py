"""Payment API serializers — read shape for GET /payments/<id>/status (Tech Spec §4)."""

from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "order_id",
            "rail",
            "status",
            "currency",
            "payment_request",
            "amount_sats",
            "amount_bif",
            "confirmed_at",
            "created_at",
        ]
        read_only_fields = fields
