from django.urls import path

from .views import PaymentStatusView

urlpatterns = [
    path("payments/<int:pk>/status", PaymentStatusView.as_view(), name="payment-status"),
]
