"""Product + inventory read endpoints (Tech Spec §4, §8 step 3/6)."""

import uuid

from django.db import IntegrityError
from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasBusiness, IsOwner

from .models import Product
from .serializers import ProductSerializer
from .services import build_product_barcode, parse_product_barcode, render_barcode_png


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


class ProductBarcodeView(APIView):
    """GET /products/<uuid:pk>/barcode → PNG image of the product's Code128 barcode.

    The barcode value (FOBOS-generated or manufacturer) is embedded as an image
    so the front can render it for printing / on-screen without client-side libs.
    """

    permission_classes = [IsAuthenticated, HasBusiness]

    def get(self, request, pk: uuid.UUID):
        product = Product.objects.filter(business=request.user.business, pk=pk).first()
        if product is None:
            return Response(
                {"detail": "Product not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not product.barcode:
            return Response(
                {"detail": "This product has no barcode."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if any(ord(char) > 127 for char in product.barcode):
            return Response(
                {
                    "code": "barcode_not_renderable",
                    "detail": "Barcode contains non-ASCII characters.",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        response = HttpResponse(render_barcode_png(product.barcode), content_type="image/png")
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


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
