from django.urls import path

from .views import (
    OnrampConfirmView,
    OnrampRequestOtpView,
    PaymentStatusView,
)
from .webhooks import BlinkWebhookView

urlpatterns = [
    path("payments/<str:order_id>/status", PaymentStatusView.as_view(), name="payment-status"),
    path(
        "payments/onramp/request-otp",
        OnrampRequestOtpView.as_view(),
        name="onramp-request-otp",
    ),
    path(
        "payments/onramp/confirm",
        OnrampConfirmView.as_view(),
        name="onramp-confirm",
    ),
    path("payments/webhooks/blink", BlinkWebhookView.as_view(), name="blink-webhook"),
]
