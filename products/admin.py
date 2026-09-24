from django.contrib import admin

from .models import Customer, Expense, Invoice, Product, Supplier


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "business",
        "barcode",
        "unit_price",
        "unit_cost",
        "stock_qty",
        "stock_threshold",
    )
    list_filter = ("business",)
    search_fields = ("name", "barcode")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "phone", "created_at")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "phone", "created_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "kind", "amount", "currency", "status")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "business", "amount", "currency", "occurred_on")
