from django.urls import path

from .views import (
    InventoryListView,
    ProductBarcodeView,
    ProductListCreateView,
    ProductScanView,
)

urlpatterns = [
    path("products", ProductListCreateView.as_view(), name="products"),
    path("products/scan/<str:barcode>", ProductScanView.as_view(), name="products-scan"),
    path("products/<uuid:pk>/barcode", ProductBarcodeView.as_view(), name="product-barcode"),
    path("inventory", InventoryListView.as_view(), name="inventory"),
]
