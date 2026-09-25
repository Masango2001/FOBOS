"""HTTP views for the SaaS layer (doc §40, §55–56; urls wired in
config/urls.py → subscriptions/urls.py, mirroring how payments is wired §28).

- plans/ + offers/: catalog reads of Plan, SubscriptionOffer.
- my/offers/: the offers FOBOS advertises to the current business.
- my/plan/: the business's current Subscription (trial or active) with the
  features it can access (§40) and the trial/paid discriminator.
- activate/: POST body {offer_id} → creates the purchase Payment
  (purpose=subscription, §41) the frontend then pays through payments/.
"""

from rest_framework import generics, viewsets
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from payments.adapters import AdapterNotInstalled
from payments.services import CheckoutError, create_subscription_payment

from .models import Plan, Subscription, SubscriptionOffer
from .permissions import feature_whitelist
from .serializers import (
    MyPlanSerializer,
    OfferPurchaseSerializer,
    PlanSerializer,
    SubscriptionOfferSerializer,
)


class _GatewayUnavailable(APIException):
    """503 — no PaymentRailAdapter is installed for the business's rail."""

    status_code = 503
    default_detail = "Payment gateway unavailable."
    default_code = "gateway_unavailable"


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Plan.objects.filter(is_active=True)
    serializer_class = PlanSerializer


class SubscriptionOfferViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SubscriptionOffer.objects.filter(is_active=True)
    serializer_class = SubscriptionOfferSerializer


class OfferViewSet(viewsets.ReadOnlyModelViewSet):
    """Offers visible to the current business (all active offers today)."""

    serializer_class = SubscriptionOfferSerializer

    def get_queryset(self):
        return SubscriptionOffer.objects.filter(is_active=True)


class MyPlanView(generics.RetrieveAPIView):
    """Current subscription of the authenticated business (§55–56)."""

    serializer_class = MyPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        business = self.request.user.business
        subscription = (
            Subscription.objects.filter(business=business)
            .exclude(status__in=["expired", "cancelled"])
            .first()
        )
        if subscription is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("No subscription for this business.")
        return subscription


class SubscriptionActivateView(generics.CreateAPIView):
    """Start a paid subscription purchase for the chosen offer (§41)."""

    permission_classes = [IsAuthenticated]
    serializer_class = OfferPurchaseSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offer_id = str(serializer.validated_data["offer_id"])
        try:
            payment = create_subscription_payment(
                user=request.user,
                offer_id=offer_id,
            )
        except CheckoutError as exc:
            raise ValidationError({"offer_id": str(exc)}) from exc
        except AdapterNotInstalled as exc:
            raise _GatewayUnavailable(str(exc)) from exc
        features = feature_whitelist("active")
        return Response(
            {
                "payment": {
                    "order_id": payment.order_id,
                    "payment_request": payment.payment_request,
                    "amount_bif": str(payment.amount_bif),
                    "amount_sats": payment.amount_sats,
                    "rail": payment.rail,
                    "currency": payment.currency,
                    "status": payment.status,
                },
                "features": features,
            },
            status=201,
        )
