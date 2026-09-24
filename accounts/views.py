from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import ResendVerificationSerializer, SignupSerializer
from .services import send_verification_email, verify_verification_token


class SignupView(generics.CreateAPIView):
    serializer_class = SignupSerializer
    permission_classes = [permissions.AllowAny]


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]

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


class ResendVerificationView(APIView):
    """Send a fresh signed link. Generic 200 response — never leaks whether the email exists."""

    permission_classes = [permissions.AllowAny]

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
