"""Subscription API serializers — shapes agreed with the Frontend (SaaS contract).

On the SaaS side a Subscription exposes only: id | plan | offer | status |
started_at | expires_at | features. status enum returned to clients: trial |
active | expired | cancelled (doc §39). `features` is the explicit whitelist the
status grants (doc §40, §53) — TRIAL gets ~30%, ACTIVE the full set. The offer
snapshot lives on the *Payment* (`lines[0]`, doc §41), not on the serializer.
"""

from rest_framework import serializers

from .models import Plan, Subscription, SubscriptionOffer
from .permissions import feature_whitelist


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "name", "unit_price", "description", "is_active"]
        read_only_fields = fields


class SubscriptionOfferSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    final_price = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionOffer
        fields = ["id", "plan", "duration_months", "discount_rate", "final_price", "is_active"]
        read_only_fields = fields

    def get_final_price(self, obj: SubscriptionOffer) -> str:
        # FinalPrice(N) = P×N×(1−D(N)) (doc §54) — computed, not hardcoded.
        return str(obj.final_price)


class MyPlanSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    offer = SubscriptionOfferSerializer(read_only=True)
    features = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "offer",
            "status",
            "started_at",
            "expires_at",
            "features",
        ]
        read_only_fields = fields

    def get_features(self, obj: Subscription) -> list[str]:
        return feature_whitelist(obj.status)


class OfferPurchaseSerializer(serializers.Serializer):
    """POST /activate — the frontend only ever sends the offer id (§41, §55)."""

    offer_id = serializers.UUIDField()
