from django.urls import path

from .views import AutomationExecutionListView, AutomationRuleListCreateView

urlpatterns = [
    path("automations", AutomationRuleListCreateView.as_view(), name="automations"),
    path(
        "automations/executions",
        AutomationExecutionListView.as_view(),
        name="automations-executions",
    ),
]
