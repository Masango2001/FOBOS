from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Business, User


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ["id", "name", "category", "settlement_preference", "lumicash_number", "blink_username"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        preference = attrs.get("settlement_preference", self.instance.settlement_preference)
        phone = attrs.get("lumicash_number", self.instance.lumicash_number)
        blink = attrs.get("blink_username", self.instance.blink_username)
        if preference == Business.SettlementPreference.BIF_LUMICASH and not phone:
            raise serializers.ValidationError({"lumicash_number": "Required for BIF settlement."})
        if preference == Business.SettlementPreference.AS_IS and not blink:
            raise serializers.ValidationError({"blink_username": "Required for Blink settlement."})
        return attrs


class AuthenticatedUserSerializer(serializers.ModelSerializer):
    business_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = ["id", "email", "name", "phone", "role", "business_id"]
        read_only_fields = fields


class SignupResponseSerializer(serializers.ModelSerializer):
    detail = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "detail"]
        read_only_fields = fields


class SignupSerializer(serializers.Serializer):
    """Create a Business + owner User on signup (Tech Spec §8 step 2)."""

    business_name = serializers.CharField(max_length=150, write_only=True)
    category = serializers.CharField(
        max_length=100, required=False, allow_blank=True, write_only=True
    )
    owner_name = serializers.CharField(max_length=150, write_only=True)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, write_only=True)
    settlement_preference = serializers.ChoiceField(
        choices=Business.SettlementPreference.choices,
        default=Business.SettlementPreference.BIF_LUMICASH,
        write_only=True,
    )
    lumicash_number = serializers.CharField(
        max_length=30, required=False, allow_blank=True, write_only=True
    )
    blink_username = serializers.CharField(
        max_length=100, required=False, allow_blank=True, write_only=True
    )

    def validate(self, attrs: dict) -> dict:
        if User.objects.filter(email=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "This email is already registered."})
        preference = attrs.get("settlement_preference", Business.SettlementPreference.BIF_LUMICASH)
        if preference == Business.SettlementPreference.BIF_LUMICASH and not attrs.get(
            "lumicash_number"
        ):
            raise serializers.ValidationError(
                {"lumicash_number": "Required when settlement_preference is bif_lumicash."}
            )
        if preference == Business.SettlementPreference.AS_IS and not attrs.get("blink_username"):
            raise serializers.ValidationError(
                {"blink_username": "Required when settlement_preference is as_is."}
            )
        return attrs

    def create(self, validated_data: dict) -> User:
        user = User.objects.create_user(
            email=validated_data["email"],
            name=validated_data["owner_name"],
            password=validated_data["password"],
            phone=validated_data.get("phone", ""),
            role=User.Role.OWNER,
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        business = Business.objects.create(
            name=validated_data["business_name"],
            category=validated_data.get("category", ""),
            owner=user,
            settlement_preference=validated_data.get(
                "settlement_preference", Business.SettlementPreference.BIF_LUMICASH
            ),
            lumicash_number=validated_data.get("lumicash_number", ""),
            blink_username=validated_data.get("blink_username", ""),
        )
        user.business = business
        user.save(update_fields=["business"])
        # Seed the demo automation rule (stock threshold → alert) at signup (§6, §8 step 1).
        from automation.services import ensure_default_rule

        ensure_default_rule(business)
        # Grant the 3-day SaaS trial (§55) — idempotent on the business.
        from subscriptions.services import create_trial

        create_trial(business=business)
        return user


class CashierCreateSerializer(serializers.ModelSerializer):
    """Owner creates a cashier who can use their account immediately."""

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "role",
            "business",
            "email_verified",
            "password",
        ]
        read_only_fields = ["role", "business", "email_verified"]

    def create(self, validated_data: dict) -> User:
        password = validated_data.pop("password")
        user = User.objects.create_user(
            email=validated_data["email"],
            name=validated_data["name"],
            password=password,
            phone=validated_data.get("phone", ""),
            role=User.Role.CASHIER,
            business=validated_data["business"],
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        return user


class CashierSerializer(serializers.ModelSerializer):
    """Read + update (PUT/PATCH) of an owner's cashier — password optional on update.

    `role`, `business` and `email_verified` are read-only: an owner cannot promote a
    cashier, move them to another business, or change the verification metadata.
    """

    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "role",
            "business",
            "email_verified",
            "password",
        ]
        read_only_fields = ["id", "role", "business", "email_verified"]

    def update(self, instance: User, validated_data: dict) -> User:
        password = validated_data.pop("password", None)
        email_changed = "email" in validated_data and validated_data["email"].lower() != (
            instance.email.lower()
        )
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        if email_changed:
            instance.email_verified = True
            instance.email_verified_at = timezone.now()
        instance.save()
        return instance


class FobosTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT pair that embeds the user's role claim (§4)."""

    def validate(self, attrs: dict) -> dict:
        return super().validate(attrs)

    @classmethod
    def get_token(cls, user: User):  # type: ignore[override]
        token = super().get_token(user)
        token["role"] = user.role
        token["business_id"] = str(user.business_id) if user.business_id is not None else None
        token["email_verified"] = user.email_verified
        return token


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
