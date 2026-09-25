from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    MyPlanView,
    OfferViewSet,
    PlanViewSet,
    SubscriptionActivateView,
    SubscriptionOfferViewSet,
)

router = DefaultRouter()
router.register("plans", PlanViewSet, basename="plan")
router.register("offers", SubscriptionOfferViewSet, basename="subscription-offer")
router.register("my/offers", OfferViewSet, basename="my-offer")

urlpatterns = [
    path("my/plan/", MyPlanView.as_view(), name="my-plan"),
    path("activate/", SubscriptionActivateView.as_view(), name="activate"),
] + router.urls
