from rest_framework import serializers

from .models import AutomationExecution, AutomationRule


class AutomationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationRule
        fields = ["id", "trigger", "condition", "action", "active", "created_at"]
        read_only_fields = ["id", "created_at"]


class AutomationExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationExecution
        fields = ["id", "rule", "financial_event", "result", "executed_at"]
