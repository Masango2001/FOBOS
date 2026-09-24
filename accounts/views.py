from typing import cast

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers

from .models import User
from .permissions import IsOwner
from .serializers import (
    CashierCreateSerializer,
    CashierSerializer,
    ResendVerificationSerializer,
    SignupSerializer,
)
from .services import send_verification_email, verify_verification_token


class SignupView(generics.CreateAPIView):
    serializer_class = SignupSerializer
    permission_classes = [permissions.AllowAny]


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={
            (200, "text/html"): OpenApiResponse(
                response=OpenApiTypes.STR,
                description="HTML confirmation page after successful or repeated verification.",
            ),
            (400, "text/html"): OpenApiResponse(
                response=OpenApiTypes.STR,
                description="HTML error page for an invalid or expired verification link.",
            ),
            (404, "text/html"): OpenApiResponse(
                response=OpenApiTypes.STR,
                description="HTML not-found page if the account for the valid token no longer exists.",
            ),
        }
    )
    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        user_id = verify_verification_token(token)
        if user_id is None:
            return HttpResponse(
                render_to_string("accounts/email_verification_invalid.html"),
                status=400,
            )
        user = get_object_or_404(User, pk=user_id)
        if user.email_verified:
            return HttpResponse(render_to_string("accounts/email_verified.html"))
        user.email_verified = True
        user.email_verified_at = timezone_now()
        user.save(update_fields=["email_verified", "email_verified_at"])
        return HttpResponse(render_to_string("accounts/email_verified.html"))


class CashierListCreateView(generics.ListCreateAPIView):
    """GET/POST /auth/cashiers — owner-only: list or create cashiers of their business.

    An owner never sees other businesses' cashiers nor their own account here
    (the queryset is scoped to role=cashier + the owner's business).
    """

    serializer_class = CashierSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CashierCreateSerializer
        return CashierSerializer

    def get_queryset(self):
        request_user = cast(User, self.request.user)
        return User.objects.filter(
            business_id=request_user.business_id, role=User.Role.CASHIER
        ).order_by("date_joined")

    def perform_create(self, serializer) -> None:
        request_user = cast(User, self.request.user)
        serializer.save(business=request_user.business)


class CashierDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/PUT/DELETE /auth/cashiers/<pk> — owner-only.

    A cashier of another business or the owner's own account resolves to 404
    (queryset scoped to role=cashier + the owner's business).
    """

    serializer_class = CashierSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        request_user = cast(User, self.request.user)
        return User.objects.filter(business_id=request_user.business_id, role=User.Role.CASHIER)


class ResendVerificationView(APIView):
    """Send a fresh signed link. Generic 200 response — never leaks whether the email exists."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=ResendVerificationSerializer,
        responses={
            200: inline_serializer(
                name="ResendVerificationResponse",
                fields={"detail": drf_serializers.CharField()},
            ),
            400: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, email_verified=False).first()
        if user is not None:
            send_verification_email(user.pk, user.email)
        return Response(
            {"detail": "If the account exists, a new verification link has been sent."},
            status=status.HTTP_200_OK,
        )


def timezone_now():
    from django.utils import timezone

    return timezone.now()
