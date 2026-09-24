"""Ledger + dashboard read views (Tech Spec §4, §8 step 6)."""

from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsOwner
from automation.models import AutomationExecution

from .models import LedgerEntry
from .serializers import LedgerEntrySerializer

ZERO = Decimal("0")


def _margin(revenue: Decimal, profit: Decimal) -> Decimal:
    """Same formula as ledger.financial.gross_margin, deterministic on aggregated data."""
    if revenue == 0:
        return ZERO
    return ((profit / revenue) * Decimal("100")).quantize(Decimal("0.01"))


class LedgerListView(APIView):
    """GET /ledger — the traceable ledger entries for the business."""

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        entries = LedgerEntry.objects.filter(business=request.user.business)
        serializer = LedgerEntrySerializer(entries, many=True)
        return Response(serializer.data)


class DashboardView(APIView):
    """GET /dashboard — today's sales, revenue, profit, cashflow, stock warnings, alerts."""

    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        business = request.user.business
        today = timezone.localdate()

        sales_today = business.sales.filter(created_at__date=today)
        today_revenue = self._sum(
            type_=LedgerEntry.MovementType.CREDIT, account="REVENUE", today=today
        )
        today_cogs = self._sum(type_=LedgerEntry.MovementType.DEBIT, account="COGS", today=today)
        credits = self._sum(type_=LedgerEntry.MovementType.CREDIT, today=today)
        debits = self._sum(type_=LedgerEntry.MovementType.DEBIT, today=today)

        profit = today_revenue - today_cogs
        margin = _margin(today_revenue, profit)

        def _fmt(value: Decimal) -> str:
            return f"{value:.2f}"

        stock_warnings = [
            {
                "id": p.id,
                "name": p.name,
                "barcode": p.barcode,
                "stock_qty": p.stock_qty,
                "stock_threshold": p.stock_threshold,
            }
            for p in business.products.all()
            if p.low_stock
        ]

        alerts = [
            {
                "id": ex.id,
                "rule_id": ex.rule_id,
                "executed_at": ex.executed_at,
                "action": ex.result.get("action"),
                "products": ex.result.get("products"),
            }
            for ex in AutomationExecution.objects.filter(rule__business=business).order_by(
                "-executed_at"
            )[:20]
            if ex.result.get("triggered") is True
        ]

        return Response(
            {
                "date": str(today),
                "today_sales_count": sales_today.count(),
                "today_sales_amount": sum((s.total_amount for s in sales_today), ZERO),
                "revenue": _fmt(today_revenue),
                "cogs": _fmt(today_cogs),
                "gross_profit": _fmt(profit),
                "gross_margin": _fmt(margin),
                "net_cashflow": _fmt(credits - debits),
                "stock_warnings": stock_warnings,
                "alerts": alerts,
            }
        )

    def _sum(
        self,
        *,
        type_: str,
        account: str | None = None,
        today,
    ) -> Decimal:
        assert not isinstance(self.request.user, AnonymousUser)
        qs = LedgerEntry.objects.filter(business=self.request.user.business, type=type_)
        if account is not None:
            qs = qs.filter(account=account)
        return qs.filter(created_at__date=today).aggregate(total=Sum("amount"))["total"] or ZERO
