from django.urls import path

from .views import (
    OnrampConfirmView,
    OnrampRequestOtpView,
    PaymentStatusView,
)
from .webhooks import blink_webhook

urlpatterns = [
    path("payments/<uuid:pk>/status", PaymentStatusView.as_view(), name="payment-status"),
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
    path("payments/webhooks/blink", blink_webhook, name="blink-webhook"),
]
