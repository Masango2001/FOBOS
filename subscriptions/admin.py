from django.contrib import admin

from .models import Plan, Subscription, SubscriptionOffer


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "unit_price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(SubscriptionOffer)
class SubscriptionOfferAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "duration_months",
        "discount_rate",
        "is_active",
    )
    list_filter = ("is_active", "duration_months")
    ordering = ("plan", "duration_months")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "plan",
        "offer",
        "status",
        "started_at",
        "expires_at",
    )
    list_filter = ("status",)
    search_fields = ("business__name",)
    readonly_fields = ("created_at", "updated_at")
