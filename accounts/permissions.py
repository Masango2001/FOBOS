"""Role-based permissions (Tech Spec §1 owner/cashier access modes)."""

from rest_framework.permissions import BasePermission

from accounts.models import User


class IsOwner(BasePermission):
    """Owner mode: dashboard, finance, inventory, automations."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.business_id is not None
            and user.role == User.Role.OWNER
        )


class HasBusiness(BasePermission):
    """Any authenticated user attached to a business (owner or cashier)."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.business_id is not None)
