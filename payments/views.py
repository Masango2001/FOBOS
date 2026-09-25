"""Payment views — GET /payments/<id>/status + Lumicash OTP on-ramp (Tech Spec §4).

Status polls the rail adapter through the PaymentRailAdapter interface (§5). Built
against the interface only — real BitLibera/Blink adapters belong to Backend Dev B
and register into the same registry. Once the rail reports the order as paid,
confirmation goes through `confirm_payment` (idempotent on order_id).

The on-ramp endpoints proxy a Lumicash-OTP adapter (`OnrampAdapter`): request-otp
asks the provider to SMS an OTP; confirm validates it and confirms the Payment.
Canonical statuses returned to clients: pending | paid | failed | expired | cancelled
(doc §5.4 / §24).
"""

import uuid
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer

from accounts.permissions import HasBusiness
from config.openapi import ApiErrorSerializer

from .adapters import AdapterNotInstalled, OnrampOtpError, get_adapter, get_onramp_adapter
from .models import Payment
from .serializers import (
    OnrampConfirmSerializer,
    OnrampRequestSerializer,
    PaymentSerializer,
)
from .services import confirm_payment

CONFIRMED_STATES = ("confirmed", "paid", "settled")
EXHAUSTED_STATES = ("failed", "expired")
ONRAMP_RAIL = "bitlibera_onramp"


class PaymentStatusView(APIView):
    permission_classes = [IsAuthenticated, HasBusiness]

    @extend_schema(
        responses={200: PaymentSerializer, 404: ApiErrorSerializer, 503: ApiErrorSerializer}
    )
    def get(self, request, pk: uuid.UUID):
        payment = Payment.objects.filter(business=request.user.business, pk=pk).first()
        if payment is None:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        if payment.status == Payment.Status.PENDING:
            try:
                adapter_status = get_adapter(payment.rail).get_status(payment.order_id)
            except AdapterNotInstalled:
                return Response(
                    {
                        "code": "adapter_not_installed",
                        "detail": f"No adapter for rail '{payment.rail}'.",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if adapter_status.status in CONFIRMED_STATES:
                confirm_payment(
                    order_id=payment.order_id,
                    amount_bif=payment.amount_bif,
                    actor=request.user.email,
                    confirmed_at=adapter_status.confirmed_at,
                )
                payment.refresh_from_db()
            elif adapter_status.status in EXHAUSTED_STATES:
                payment.status = (
                    Payment.Status.EXPIRED
                    if adapter_status.status == "expired"
                    else Payment.Status.FAILED
                )
                payment.save(update_fields=["status"])

        return Response(PaymentSerializer(payment).data)


class OnrampRequestOtpView(APIView):
    """POST /payments/onramp/request-otp → customer receives an SMS OTP."""

    permission_classes = [IsAuthenticated, HasBusiness]

    @extend_schema(
        request=OnrampRequestSerializer,
        responses={
            200: inline_serializer(
                name="OnrampRequestOtpResponse",
                fields={
                    "status": serializers.CharField(),
                    "demo_otp": serializers.CharField(required=False, allow_null=True),
                },
            ),
            400: OpenApiTypes.OBJECT,
            503: ApiErrorSerializer,
        },
    )
    def post(self, request):
        serializer = OnrampRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            adapter = get_onramp_adapter(ONRAMP_RAIL)
        except AdapterNotInstalled:
            return Response(
                {"code": "adapter_not_installed", "detail": "On-ramp adapter is not installed."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        sent = adapter.request_otp(
            customer_phone=serializer.validated_data["customer_phone"],
            amount=serializer.validated_data["amount"],
        )
        body = {"status": sent.status}
        if sent.demo_otp is not None:
            body["demo_otp"] = sent.demo_otp
        return Response(body, status=status.HTTP_200_OK)


class OnrampConfirmView(APIView):
    """POST /payments/onramp/confirm → validates the OTP and confirms the order."""

    permission_classes = [IsAuthenticated, HasBusiness]

    @extend_schema(
        request=OnrampConfirmSerializer,
        responses={
            200: PaymentSerializer,
            400: OpenApiTypes.OBJECT,
            404: ApiErrorSerializer,
            503: ApiErrorSerializer,
        },
    )
    def post(self, request):
        serializer = OnrampConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = Payment.objects.filter(
            business=request.user.business, order_id=data["order_id"]
        ).first()
        if payment is None:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        if payment.status == Payment.Status.PAID:
            # Idempotent retry (PRD §32): the OTP was already consumed, the order is done.
            return Response(PaymentSerializer(payment).data, status=status.HTTP_200_OK)
        try:
            adapter = get_onramp_adapter(ONRAMP_RAIL)
        except AdapterNotInstalled:
            return Response(
                {"code": "adapter_not_installed", "detail": "On-ramp adapter is not installed."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            adapter.confirm_otp(
                customer_phone=data["customer_phone"],
                amount=data["amount"],
                otp=data["otp"],
            )
        except OnrampOtpError as exc:
            return Response(
                {"code": exc.code, "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        confirm_payment(
            order_id=payment.order_id,
            amount_bif=payment.amount_bif,
            actor=request.user.email,
        )
        payment.refresh_from_db()
        return Response(PaymentSerializer(payment).data, status=status.HTTP_200_OK)
