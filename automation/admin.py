from django.contrib import admin

from .models import AutomationExecution, AutomationRule


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ("business", "trigger", "action", "active", "created_at")
    list_filter = ("active", "trigger")


@admin.register(AutomationExecution)
class AutomationExecutionAdmin(admin.ModelAdmin):
    list_display = ("id", "rule", "financial_event", "executed_at")
