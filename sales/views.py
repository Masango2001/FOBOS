"""Sales views — POST /cart/checkout (Tech Spec §4)."""

from django.db import DatabaseError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasBusiness
from payments.adapters import AdapterNotInstalled
from payments.services import CheckoutError, InsufficientStock, create_checkout_payment

from .serializers import CheckoutSerializer


class CheckoutView(APIView):
    """POST /cart/checkout → { payment_request, order_id, rail } (§3 step 1)."""

    permission_classes = [IsAuthenticated, HasBusiness]

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
            )
        except AdapterNotInstalled as exc:
            return Response(
                {"code": "adapter_not_installed", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
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
        return Response(
            {
                "id": payment.id,
                "payment_request": payment.payment_request,
                "order_id": payment.order_id,
                "rail": payment.rail,
                "status": payment.status,
                "amount": f"{payment.total_amount:.2f}",
                "currency": payment.currency,
            },
            status=status.HTTP_201_CREATED,
        )
