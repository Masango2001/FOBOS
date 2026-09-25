"""Sales views — POST /cart/checkout (Tech Spec §4)."""

from django.db import DatabaseError
from rest_framework import serializers, status
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer

from accounts.permissions import HasBusiness
from config.openapi import ApiErrorSerializer
from payments.adapters import AdapterNotInstalled
from payments.live import ProviderError
from payments.serializers import PaymentSerializer
from payments.services import CheckoutError, InsufficientStock, create_checkout_payment

from .models import Receipt, Sale
from .serializers import CheckoutSerializer, ReceiptSerializer, SaleSerializer


class SaleListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, HasBusiness]
    serializer_class = SaleSerializer

    def get_queryset(self):
        queryset = Sale.objects.filter(business=self.request.user.business).select_related("cashier", "financial_event").prefetch_related("sale_lines__product")
        start = self.request.query_params.get("date_from")
        end = self.request.query_params.get("date_to")
        if start:
            queryset = queryset.filter(created_at__date__gte=start)
        if end:
            queryset = queryset.filter(created_at__date__lte=end)
        return queryset


class SaleDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, HasBusiness]
    serializer_class = SaleSerializer

    def get_queryset(self):
        return Sale.objects.filter(business=self.request.user.business).select_related("cashier", "financial_event").prefetch_related("sale_lines__product")


class ReceiptDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, HasBusiness]
    serializer_class = ReceiptSerializer

    def get_queryset(self):
        return Receipt.objects.filter(sale__business=self.request.user.business)


class CheckoutView(APIView):
    """POST /cart/checkout → { payment_request, order_id, rail } (§3 step 1)."""

    permission_classes = [IsAuthenticated, HasBusiness]

    @extend_schema(
        request=CheckoutSerializer,
        responses={
            201: inline_serializer(
                name="CheckoutResponse",
                fields={
                    "order_id": serializers.CharField(),
                    "payment_request": serializers.CharField(),
                    "rail": serializers.CharField(),
                    "payment_method": serializers.ChoiceField(choices=["qr", "lumicash_otp", "cash"]),
                    "amount_bif": serializers.IntegerField(allow_null=True),
                    "amount_sats": serializers.IntegerField(allow_null=True),
                    "settlement_currency": serializers.CharField(),
                    "settlement_amount": serializers.DecimalField(
                        max_digits=24, decimal_places=8, allow_null=True
                    ),
                    "exchange_rate": serializers.DecimalField(
                        max_digits=24, decimal_places=12, allow_null=True
                    ),
                    "rate_source": serializers.CharField(),
                    "rate_timestamp": serializers.DateTimeField(allow_null=True),
                    "change": serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True),
                    "status": serializers.CharField(),
                    "receipt": serializers.JSONField(allow_null=True),
                },
            ),
            400: OpenApiTypes.OBJECT,
            409: ApiErrorSerializer,
            500: ApiErrorSerializer,
            503: ApiErrorSerializer,
            502: ApiErrorSerializer,
        },
    )
    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payment = create_checkout_payment(
                user=request.user,
                lines=data.get("lines"),
                amount=data.get("amount"),
                currency=data.get("currency", "BIF"),
                payment_method=data.get("payment_method", "qr"),
                customer_phone=data.get("customer_phone", ""),
                amount_tendered=data.get("amount_tendered"),
            )
        except AdapterNotInstalled as exc:
            return Response(
                {"code": "adapter_not_installed", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ProviderError as exc:
            return Response(
                {"code": "provider_unavailable", "detail": str(exc)},
                status=502,
            )
        except InsufficientStock as exc:
            return Response(
                {"code": exc.code, "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except CheckoutError as exc:
            return Response(
                {"code": exc.code, "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DatabaseError:
            return Response(
                {"code": "checkout_failed", "detail": "Checkout could not be recorded."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        payment_data = PaymentSerializer(payment).data
        return Response(
            {
                "order_id": payment.order_id,
                "payment_request": payment.payment_request,
                "rail": payment.rail,
                "payment_method": data.get("payment_method", "qr"),
                "amount_bif": payment.amount_bif,
                "amount_sats": payment.amount_sats,
                "settlement_currency": payment_data["settlement_currency"],
                "settlement_amount": payment_data["settlement_amount"],
                "exchange_rate": payment_data["exchange_rate"],
                "rate_source": payment_data["rate_source"],
                "rate_timestamp": payment_data["rate_timestamp"],
                "status": payment.status,
                "receipt": payment_data["receipt"],
                "change": (
                    str(payment.amount_tendered - payment.total_amount)
                    if payment.rail == "cash" and payment.amount_tendered is not None
                    else None
                ),
            },
            status=status.HTTP_201_CREATED,
        )
