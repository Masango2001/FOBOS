from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsOwner

from .models import AutomationExecution, AutomationRule
from .serializers import AutomationExecutionSerializer, AutomationRuleSerializer
from .services import ensure_default_rule


class AutomationRuleListCreateView(generics.ListCreateAPIView):
    """GET/POST /automations (Tech Spec §4, owner only)."""

    serializer_class = AutomationRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        business = self.request.user.business
        ensure_default_rule(business)
        return AutomationRule.objects.filter(business=business)

    def perform_create(self, serializer):
        serializer.save(business=self.request.user.business)


class AutomationExecutionListView(APIView):
    """GET /automations/executions (Tech Spec §4, owner only)."""

    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get(self, request):
        ensure_default_rule(request.user.business)
        executions = AutomationExecution.objects.filter(rule__business=request.user.business)
        serializer = AutomationExecutionSerializer(executions, many=True)
        return Response(serializer.data)
