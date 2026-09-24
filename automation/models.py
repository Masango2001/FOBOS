"""Automation engine models (Tech Spec §2, §6).

MVP scope: one hardcoded rule type (stock threshold → alert). The table/interface
is visibly generic (trigger/condition/action) but there is NO condition-parser
DSL — that is explicitly Phase 2.
"""

from django.db import models

from accounts.models import Business
from ledger.models import FinancialEvent


class AutomationRule(models.Model):
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="automation_rules"
    )
    trigger = models.CharField(max_length=64, default="payment_confirmed")
    condition = models.JSONField(default=dict, blank=True)
    action = models.CharField(max_length=64, default="notify_merchant")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.trigger} → {self.action} ({self.pk})"


class AutomationExecution(models.Model):
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="executions")
    financial_event = models.ForeignKey(
        FinancialEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="automation_executions",
    )
    result = models.JSONField(default=dict, blank=True)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-executed_at"]

    def __str__(self) -> str:
        return f"Execution #{self.pk} rule={self.rule_id}"
