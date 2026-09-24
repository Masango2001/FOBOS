from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Business, User
from .services import send_verification_email


class EmailNotVerifiedError(AuthenticationFailed):
    """Raised by the login serializer when the account is unverified."""

    default_detail = "Email not verified. Check your inbox for the verification link."
    default_code = "email_not_verified"


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
        send_verification_email(user.pk, user.email)
        return user


class CashierCreateSerializer(serializers.ModelSerializer):
    """Owner creates a cashier for their business — email verified before first login."""

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
        )
        send_verification_email(user.pk, user.email)
        return user


class FobosTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT pair that refuses unverified emails and embeds the role claim (§4)."""

    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        user = self.user
        if user is not None and not user.email_verified:
            raise EmailNotVerifiedError()
        return data

    @classmethod
    def get_token(cls, user: User):  # type: ignore[override]
        token = super().get_token(user)
        token["role"] = user.role
        token["business_id"] = user.business_id
        token["email_verified"] = user.email_verified
        return token


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
