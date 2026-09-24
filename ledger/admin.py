from django.contrib import admin

from .models import FinancialEvent, LedgerEntry


@admin.register(FinancialEvent)
class FinancialEventAdmin(admin.ModelAdmin):
    list_display = ("type", "business", "amount", "currency", "source", "status", "timestamp")
    list_filter = ("type", "source", "status")
    search_fields = ("reference", "actor")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("type", "account", "business", "amount", "currency", "created_at")
    list_filter = ("type", "account")
