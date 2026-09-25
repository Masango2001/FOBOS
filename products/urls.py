from django.urls import path

from .movement_views import StockAdjustmentView, StockMovementListView, StockRestockView
from .views import InventoryListView, ProductDetailView, ProductListCreateView, ProductScanView

urlpatterns = [
    path("products", ProductListCreateView.as_view(), name="products"),
    path("products/scan/<str:barcode>", ProductScanView.as_view(), name="products-scan"),
    path("products/<uuid:pk>", ProductDetailView.as_view(), name="product-detail"),
    path("inventory", InventoryListView.as_view(), name="inventory"),
    path("inventory/movements", StockMovementListView.as_view(), name="inventory-movements"),
    path("inventory/adjustments", StockAdjustmentView.as_view(), name="inventory-adjustments"),
    path("inventory/restock", StockRestockView.as_view(), name="inventory-restock"),
]
