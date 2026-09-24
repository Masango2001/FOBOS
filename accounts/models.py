from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user — email is the login identifier (Tech Spec §2)."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        CASHIER = "cashier", "Cashier"

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True, default="")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)
    business = models.ForeignKey(
        "Business",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    def __str__(self) -> str:
        return self.email


class Business(models.Model):
    """Business owned by a merchant — settlement preference captured day one (Tech Spec §2)."""

    class SettlementPreference(models.TextChoices):
        AS_IS = "as_is", "Receive as-is"
        BIF_LUMICASH = "bif_lumicash", "Auto-convert to BIF"

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True, default="")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_businesses")
    created_at = models.DateTimeField(auto_now_add=True)
    settlement_preference = models.CharField(
        max_length=20,
        choices=SettlementPreference.choices,
        default=SettlementPreference.BIF_LUMICASH,
    )
    lumicash_number = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Required when settlement_preference = bif_lumicash",
    )
    blink_username = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Required when settlement_preference = as_is",
    )
    bitlibera_merchant_id = models.CharField(max_length=100, blank=True, default="")
    bitlibera_api_key = models.CharField(max_length=255, blank=True, default="")

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if (
            self.settlement_preference == self.SettlementPreference.BIF_LUMICASH
            and not self.lumicash_number
        ):
            raise ValidationError("lumicash_number is required for bif_lumicash settlement.")
        if (
            self.settlement_preference == self.SettlementPreference.AS_IS
            and not self.blink_username
        ):
            raise ValidationError("blink_username is required for as_is settlement.")

    def __str__(self) -> str:
        return self.name
