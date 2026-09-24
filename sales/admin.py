from django.contrib import admin

from .models import Receipt, Sale, SaleLine


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "total_amount", "currency", "cashier", "created_at")
    list_filter = ("currency", "business")
    inlines = [SaleLineInline]


@admin.register(SaleLine)
class SaleLineAdmin(admin.ModelAdmin):
    list_display = ("id", "sale", "product", "quantity", "unit_price", "unit_cost")


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "sale", "created_at")
