from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order_id", "rail", "business", "status", "currency", "created_at")
    list_filter = ("rail", "status")
    search_fields = ("order_id", "lumicash_phone")
