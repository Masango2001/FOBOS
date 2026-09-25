from django.urls import path

from .views import CheckoutView, ReceiptDetailView, SaleDetailView, SaleListView

urlpatterns = [
    path("cart/checkout", CheckoutView.as_view(), name="cart-checkout"),
    path("sales", SaleListView.as_view(), name="sales-list"),
    path("sales/<uuid:pk>", SaleDetailView.as_view(), name="sales-detail"),
    path("receipts/<uuid:pk>", ReceiptDetailView.as_view(), name="receipt-detail"),
]
