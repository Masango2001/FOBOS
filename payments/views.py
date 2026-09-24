"""Payment status view — GET /payments/<id>/status (Tech Spec §4).

Polls the rail adapter through the PaymentRailAdapter interface (§5). Built
against the interface only — real BitLibera/Blink adapters belong to Backend
Dev B and register into the same registry. Once the rail reports the order as
paid, confirmation goes through `confirm_payment` (idempotent on order_id).
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasBusiness

from .adapters import AdapterNotInstalled, get_adapter
from .models import Payment
from .serializers import PaymentSerializer
from .services import confirm_payment

CONFIRMED_STATES = ("confirmed", "paid", "settled")


class PaymentStatusView(APIView):
    permission_classes = [IsAuthenticated, HasBusiness]

    def get(self, request, pk: int):
        payment = Payment.objects.filter(business=request.user.business, pk=pk).first()
        if payment is None:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        if payment.status != Payment.Status.CONFIRMED:
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

        return Response(PaymentSerializer(payment).data)
