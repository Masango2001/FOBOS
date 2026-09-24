from django.urls import path

from .views import CheckoutView

urlpatterns = [
    path("cart/checkout", CheckoutView.as_view(), name="cart-checkout"),
]
