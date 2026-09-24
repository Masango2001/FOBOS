"""Product + inventory read endpoints (Tech Spec §4, §8 step 3/6)."""

from django.db import IntegrityError
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasBusiness, IsOwner

from .models import Product
from .serializers import ProductSerializer


class ProductListCreateView(generics.ListCreateAPIView):
    """GET/POST /products — POST is owner-only (inventory is owner mode, §17)."""

    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, HasBusiness]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsOwner()]
        return [IsAuthenticated(), HasBusiness()]

    def get_queryset(self):
        return Product.objects.filter(business=self.request.user.business)

    def perform_create(self, serializer):
        try:
            serializer.save(business=self.request.user.business)
        except IntegrityError:
            raise ValidationError(
                {"barcode": "A product with this barcode already exists for your business."}
            ) from None


class ProductScanView(APIView):
    """GET /products/scan/:barcode — cashier mode needs this to build a cart."""

    permission_classes = [IsAuthenticated, HasBusiness]

    def get(self, request, barcode: str):
        product = Product.objects.filter(business=request.user.business, barcode=barcode).first()
        if product is None:
            return Response(
                {"detail": "No product matches this barcode."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ProductSerializer(product).data)


class InventoryListView(APIView):
    """GET /inventory — products with stock, value, low-stock flags (owner only)."""

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        products = Product.objects.filter(business=request.user.business)
        data = [
            {
                "id": p.id,
                "name": p.name,
                "barcode": p.barcode,
                "unit_cost": p.unit_cost,
                "unit_price": p.unit_price,
                "stock_qty": p.stock_qty,
                "stock_threshold": p.stock_threshold,
                "inventory_value": p.inventory_value,
                "low_stock": p.low_stock,
                "created_at": p.created_at,
            }
            for p in products
        ]
        return Response(data)
