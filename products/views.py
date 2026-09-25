"""Product + inventory read endpoints (Tech Spec §4, §8 step 3/6)."""

from django.db import IntegrityError
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer

from accounts.permissions import HasBusiness, IsOwner
from config.openapi import ApiErrorSerializer

from .models import Product
from .serializers import ProductSerializer
from .services import build_product_barcode, parse_product_barcode


class ProductListCreateView(generics.ListCreateAPIView):
    """GET/POST /products — POST is owner-only (inventory is owner mode, §17).

    A product created without a manufacturer barcode gets a FOBOS-generated one
    embedding name | unit_price | product id (products/services.py).
    """

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
            product = serializer.save(business=self.request.user.business)
            if not product.barcode:
                product.barcode = build_product_barcode(
                    name=product.name, price=product.unit_price, product_id=product.id
                )
                product.save(update_fields=["barcode"])
            # LOT 1 rule 5 (/inventory == sum(qty_delta)) is guaranteed by the
            # products.post_save signal, which records the initial "restock"
            # movement for any created product with stock_qty > 0.
        except IntegrityError:
            raise ValidationError(
                {"barcode": "A product with this barcode already exists for your business."}
            ) from None


class ProductScanView(APIView):
    """GET /products/scan/:barcode — cashier mode needs this to build a cart.

    Resolves FOBOS barcodes by their embedded product id (authoritative), then
    falls back to an exact barcode match for manufacturer codes.
    """

    permission_classes = [IsAuthenticated, HasBusiness]

    @extend_schema(
        parameters=[OpenApiParameter("barcode", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: ProductSerializer, 404: ApiErrorSerializer},
    )
    def get(self, request, barcode: str):
        business = request.user.business
        product = None
        payload = parse_product_barcode(barcode)
        if payload is not None:
            product = Product.objects.filter(business=business, pk=payload.product_id).first()
        if product is None:
            product = Product.objects.filter(business=business, barcode=barcode).first()
        if product is None:
            return Response(
                {"detail": "No product matches this barcode."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ProductSerializer(product).data)


class InventoryListView(APIView):
    """GET /inventory — products with stock, value, low-stock flags (owner only)."""

    permission_classes = [IsAuthenticated, IsOwner]

    @extend_schema(
        responses={
            200: inline_serializer(
                name="InventoryItem",
                many=True,
                fields={
                    "id": serializers.UUIDField(),
                    "name": serializers.CharField(),
                    "barcode": serializers.CharField(allow_null=True),
                    "barcode_image_url": serializers.CharField(allow_null=True),
                    "unit_cost": serializers.DecimalField(max_digits=20, decimal_places=2),
                    "unit_price": serializers.DecimalField(max_digits=20, decimal_places=2),
                    "stock_qty": serializers.IntegerField(),
                    "stock_threshold": serializers.IntegerField(),
                    "inventory_value": serializers.DecimalField(max_digits=20, decimal_places=2),
                    "low_stock": serializers.BooleanField(),
                    "created_at": serializers.DateTimeField(),
                },
            )
        }
    )
    def get(self, request):
        products = Product.objects.filter(business=request.user.business)
        data = [
            {
                "id": p.id,
                "name": p.name,
                "barcode": p.barcode,
                "barcode_image_url": (p.barcode_image.url if p.barcode_image else None),
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
