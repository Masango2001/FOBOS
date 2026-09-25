from django.urls import path
from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import EmailNotVerifiedError, FobosTokenObtainPairSerializer
from .views import (
    CashierDetailView,
    CashierListCreateView,
    BusinessView,
    CurrentUserView,
    ResendVerificationView,
    SignupView,
    VerifyEmailView,
)


class FobosTokenObtainPairView(TokenObtainPairView):
    serializer_class = FobosTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except EmailNotVerifiedError:
            return Response(
                {
                    "detail": "Email not verified. Check your inbox for the verification link.",
                    "code": "email_not_verified",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )


urlpatterns = [
    path("signup", SignupView.as_view(), name="auth-signup"),
    path("login", FobosTokenObtainPairView.as_view(), name="auth-login"),
    path("token/refresh", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("business", BusinessView.as_view(), name="business-profile"),
    path("me", CurrentUserView.as_view(), name="auth-me"),
    path("cashiers", CashierListCreateView.as_view(), name="auth-cashiers"),
    path("cashiers/<uuid:pk>", CashierDetailView.as_view(), name="auth-cashiers-detail"),
    path(
        "verify-email/<str:token>/",
        VerifyEmailView.as_view(),
        name="auth-verify-email",
    ),
    path(
        "resend-verification",
        ResendVerificationView.as_view(),
        name="auth-resend-verification",
    ),
]
