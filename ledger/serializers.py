from rest_framework import serializers

from .models import LedgerEntry


class LedgerEntrySerializer(serializers.ModelSerializer):
    financial_event_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "type",
            "account",
            "amount",
            "currency",
            "financial_event_id",
            "created_at",
        ]
