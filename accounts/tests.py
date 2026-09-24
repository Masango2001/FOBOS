import pytest
from django.core import mail
from django.core.mail.message import EmailMultiAlternatives
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from .models import Business, User
from .services import build_verification_token

SIGNUP_PAYLOAD = {
    "business_name": "Chez Alice",
    "category": "Retail",
    "owner_name": "Alice",
    "email": "alice@example.com",
    "password": "supersecret123",
    "phone": "+25770000000",
    "settlement_preference": "bif_lumicash",
    "lumicash_number": "+25771111111",
}


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_signup_creates_user_business_and_sends_verification_email(client: APIClient) -> None:
    response = client.post("/auth/signup", SIGNUP_PAYLOAD, format="json")

    assert response.status_code == 201
    user = User.objects.get(email="alice@example.com")
    assert user.role == User.Role.OWNER
    assert user.email_verified is False
    business = Business.objects.get(owner=user)
    assert business.name == "Chez Alice"
    assert business.settlement_preference == Business.SettlementPreference.BIF_LUMICASH
    assert user.business_id == business.id
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    if not isinstance(message, EmailMultiAlternatives):
        pytest.fail("expected an EmailMultiAlternatives message")
    html = str(message.alternatives[0][0])
    assert "Vérifier mon email" in html
    assert "http://localhost:8000/auth/verify-email/" in html


@pytest.mark.django_db
def test_signup_requires_lumicash_number_when_bif_lumicash(client: APIClient) -> None:
    payload = dict(SIGNUP_PAYLOAD)
    payload.pop("lumicash_number")
    response = client.post("/auth/signup", payload, format="json")
    assert response.status_code == 400
    assert "lumicash_number" in response.json()


@pytest.mark.django_db
def test_verify_email_marks_user_verified(client: APIClient) -> None:
    user = User.objects.create_user(email="bob@example.com", name="Bob", password="supersecret123")
    token = build_verification_token(user.pk)
    response = client.get(f"/auth/verify-email/{token}/")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email_verified is True
    assert user.email_verified_at is not None
    assert "Email vérifié" in response.content.decode()


@pytest.mark.django_db
def test_verify_email_rejects_invalid_token(client: APIClient) -> None:
    response = client.get("/auth/verify-email/garbage-token/")
    assert response.status_code == 400


@pytest.mark.django_db
@override_settings(EMAIL_VERIFICATION_MAX_AGE_SECONDS=-1)
def test_verify_email_rejects_expired_token(client: APIClient) -> None:
    user = User.objects.create_user(
        email="carol@example.com", name="Carol", password="supersecret123"
    )
    token = build_verification_token(user.pk)
    response = client.get(f"/auth/verify-email/{token}/")
    assert response.status_code == 400


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_login_blocked_before_verification(client: APIClient) -> None:
    User.objects.create_user(email="dave@example.com", name="Dave", password="supersecret123")
    response = client.post(
        "/auth/login",
        {"email": "dave@example.com", "password": "supersecret123"},
        format="json",
    )
    assert response.status_code == 401
    assert "email_not_verified" in response.json().get("code", "")


@pytest.mark.django_db
def test_login_works_after_verification(client: APIClient) -> None:
    user = User.objects.create_user(
        email="erin@example.com", name="Erin", password="supersecret123"
    )
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    business = Business.objects.create(name="B", owner=user)
    user.business = business
    user.save(update_fields=["business"])
    response = client.post(
        "/auth/login",
        {"email": "erin@example.com", "password": "supersecret123"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert "access" in body and "refresh" in body
    token = AccessToken(body["access"])
    assert token["role"] == "owner"
    assert token["business_id"] == business.id
    assert token["email_verified"] is True
