"""Product + inventory read endpoints (Tech Spec §4, §8 step 3/6)."""

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
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
from .services import (
    BARCODE_PREFIX,
    build_internal_ean13,
    build_product_barcode,
    parse_product_barcode,
)


class ProductListCreateView(generics.ListCreateAPIView):
    """GET/POST /products — POST is owner-only (inventory is owner mode, §17).

    A product created without a manufacturer barcode gets an internal-use EAN-13.
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
                product.barcode = build_internal_ean13(
                    product_id=product.id, business_id=product.business_id
                )
                product.save(update_fields=["barcode"])
            # LOT 1 rule 5 (/inventory == sum(qty_delta)) is guaranteed by the
            # products.post_save signal, which records the initial "restock"
            # movement for any created product with stock_qty > 0.
        except IntegrityError:
            raise ValidationError(
                {"barcode": "A product with this barcode already exists for your business."}
            ) from None


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/PUT/DELETE /products/:id — reads for any business user, writes owner-only.

    Queryset is business-scoped, so a cross-business lookup returns 404 (same
    isolation guarantee as the list). A FOBOS-generated barcode (prefixed "F.")
    is regenerated on every write that does not supply a new barcode, so the
    code always matches the latest name / price / product id.
    """

    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, HasBusiness]

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT", "DELETE"):
            return [IsAuthenticated(), IsOwner()]
        return [IsAuthenticated(), HasBusiness()]

    def get_queryset(self):
        return Product.objects.filter(business=self.request.user.business)

    def perform_update(self, serializer) -> None:
        try:
            product = serializer.save()
            if product.barcode and product.barcode.startswith(BARCODE_PREFIX):
                # Keep a FOBOS-generated code in sync with the updated fields;
                # manufacturer codes are never overwritten.
                payload = parse_product_barcode(product.barcode)
                if payload is None or (
                    payload.name != product.name[:24]
                    or payload.price != str(product.unit_price)
                    or payload.product_id != str(product.id)
                ):
                    product.barcode = build_product_barcode(
                        name=product.name, price=product.unit_price, product_id=product.id
                    )
                    product.save(update_fields=["barcode"])
        except IntegrityError:
            raise ValidationError(
                {"barcode": "A product with this barcode already exists for your business."}
            ) from None

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Cannot delete: product has stock movements or sale lines."},
                status=status.HTTP_409_CONFLICT,
            )


class ProductScanView(APIView):
    """GET /products/scan/:barcode — cashier mode needs this to build a cart.

    Resolves legacy FOBOS codes by embedded product id, then matches current
    internal EAN-13 and manufacturer codes against this business's catalog.
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
