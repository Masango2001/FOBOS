from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.models import BaseUserManager

if TYPE_CHECKING:
    from .models import User


class UserManager(BaseUserManager["User"]):
    """Manager for the custom User model (email login)."""

    use_in_migrations = True

    def create_user(
        self, email: str, name: str, password: str | None = None, **extra_fields: object
    ) -> "User":
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password if password else "")
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, name: str, password: str | None = None, **extra_fields: object
    ) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("email_verified", True)
        return self.create_user(email, name, password, **extra_fields)
