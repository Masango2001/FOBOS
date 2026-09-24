from django.contrib import admin

from .models import Business, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "role", "business", "email_verified", "is_active")
    search_fields = ("email", "name")


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "owner", "settlement_preference")
    search_fields = ("name",)
