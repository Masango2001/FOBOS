from django.urls import path

from .views import DashboardView, LedgerListView

urlpatterns = [
    path("ledger", LedgerListView.as_view(), name="ledger"),
    path("dashboard", DashboardView.as_view(), name="dashboard"),
]
