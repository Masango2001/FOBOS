"""Stock movement endpoints (LOT 1).

GET  /inventory/movements?product_id=&type=&limit=&cursor=  → cursor-paginated ledger
POST /inventory/adjustments                                 → owner applies a manual
  stock correction; every correction is recorded as an append-only movement.
"""

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer

from accounts.permissions import HasBusiness, IsOwner
from config.openapi import ApiErrorSerializer

from .models import Product, StockMovement
from .movements import (
    AdjustmentReasonRequiredError,
    NegativeStockError,
    apply_stock_movement,
)
from .serializers import (
    ProductSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    StockRestockSerializer,
)


class StockMovementListView(APIView):
    """GET /inventory/movements — cursor-paginated append-only stock ledger.

    Read access for any business user (owner or cashier); writes are owner-only.
    """

    permission_classes = [IsAuthenticated, HasBusiness]

    @extend_schema(
        parameters=[
            OpenApiParameter("product_id", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=list(StockMovement.MovementType.values),
            ),
            OpenApiParameter(
                "limit",
                {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                OpenApiParameter.QUERY,
                description="Page size from 1 to 200; defaults to 50.",
            ),
            OpenApiParameter(
                "cursor",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Opaque cursor returned as next_cursor by the previous page.",
            ),
        ],
        responses={
            200: inline_serializer(
                name="StockMovementPage",
                fields={
                    "items": StockMovementSerializer(many=True),
                    "next_cursor": serializers.CharField(allow_null=True),
                },
            ),
            400: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        business = request.user.business
        qs = StockMovement.objects.filter(business=business)

        product_id = request.query_params.get("product_id")
        movement_type = request.query_params.get("type")
        if product_id:
            qs = qs.filter(product_id=product_id)
        if movement_type:
            if movement_type not in StockMovement.MovementType.values:
                raise ValidationError({"type": f"Invalid movement type: {movement_type!r}."})
            qs = qs.filter(type=movement_type)

        limit = _coerce_limit(request.query_params.get("limit", "50"))
        cursor = _decode_cursor(request.query_params.get("cursor"))

        # Cursor = last seen created_at/id (keyset pagination, stable ordering).
        if cursor is not None:
            from django.db.models import Q

            qs = qs.filter(
                Q(created_at__lt=cursor["created_at"])
                | Q(created_at=cursor["created_at"], id__lt=cursor["pk"])
            )
        page = list(qs[: limit + 1])
        has_more = len(page) > limit
        items = page[:limit]
        next_cursor = None
        if has_more and items:
            next_cursor = _encode_cursor(items[-1])
        return Response(
            {"items": StockMovementSerializer(items, many=True).data, "next_cursor": next_cursor}
        )


class _StockMutationView(APIView):
    """Shared owner-only logic: apply a stock movement and return movement + product."""

    permission_classes = [IsAuthenticated, IsOwner]
    serializer_class: type[serializers.Serializer] | None = None
    movement_type: StockMovement.MovementType | None = None
    quantity_field = "qty_delta"

    @extend_schema(
        responses={
            201: inline_serializer(
                name="StockMutationResponse",
                fields={
                    "movement": StockMovementSerializer(),
                    "product": ProductSerializer(),
                },
            ),
            400: OpenApiTypes.OBJECT,
            409: ApiErrorSerializer,
        }
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        business = request.user.business
        product_id = str(data["product_id"])
        product = Product.objects.filter(business=business, pk=product_id).first()
        if product is None:
            raise ValidationError({"product_id": "No product found for this business."})
        try:
            with transaction.atomic():
                movement = apply_stock_movement(
                    product=Product.objects.select_for_update().get(pk=product.pk),
                    movement_type=self.movement_type,
                    qty_delta=int(data[self.quantity_field]),
                    reason=data["reason"],
                )
        except NegativeStockError as exc:
            # LOT 1 rule 2: stock can never go negative → 409 Conflict.
            return Response(
                {
                    "code": "negative_stock",
                    "detail": (
                        f"Stock would go negative: current {exc.current_stock}, "
                        f"delta {exc.qty_delta}."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except AdjustmentReasonRequiredError:
            raise ValidationError({"reason": "Required for this movement type."}) from None

        product.refresh_from_db()
        return Response(
            {
                "movement": StockMovementSerializer(movement).data,
                "product": ProductSerializer(product).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StockAdjustmentView(_StockMutationView):
    """POST /inventory/adjustments — owner applies a manual stock correction."""

    serializer_class = StockAdjustmentSerializer
    movement_type = StockMovement.MovementType.ADJUSTMENT


class StockRestockView(_StockMutationView):
    """POST /inventory/restock — owner restocks a product (positive qty only)."""

    serializer_class = StockRestockSerializer
    movement_type = StockMovement.MovementType.RESTOCK
    quantity_field = "quantity"


def _coerce_limit(raw: str) -> int:
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({"limit": "Must be an integer."}) from None
    if limit < 1 or limit > 200:
        raise ValidationError({"limit": "Must be between 1 and 200."})
    return limit


def _encode_cursor(movement) -> str:
    import base64

    raw = f"{movement.created_at.isoformat()}|{movement.pk}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(raw: str | None):
    if not raw:
        return None
    import base64

    from django.core.exceptions import ValidationError as _VE

    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
        created_at_iso, pk = decoded.rsplit("|", 1)
    except Exception:
        raise ValidationError({"cursor": "Invalid cursor."}) from None
    from datetime import datetime

    from django.utils import timezone

    try:
        created_at = datetime.fromisoformat(created_at_iso)
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at)
        return {"created_at": created_at, "pk": pk}
    except (ValueError, _VE):
        raise ValidationError({"cursor": "Invalid cursor."}) from None
