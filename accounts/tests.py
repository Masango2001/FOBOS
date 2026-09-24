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
    assert token["business_id"] == str(business.id)
    assert token["email_verified"] is True


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_owner_creates_cashier_with_verification_email(owner_client: APIClient) -> None:
    response = owner_client.post(
        "/auth/cashiers",
        {
            "name": "Bob",
            "email": "bob@example.com",
            "phone": "+25771111111",
            "password": "supersecret123",
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "cashier"
    assert body["email_verified"] is False
    assert "password" not in body
    user = User.objects.get(email="bob@example.com")
    assert user.role == User.Role.CASHIER
    assert str(user.business_id) == body["business"]
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    if not isinstance(message, EmailMultiAlternatives):
        pytest.fail("expected an EmailMultiAlternatives message")
    html = str(message.alternatives[0][0])
    assert "http://localhost:8000/auth/verify-email/" in html


@pytest.mark.django_db
def test_cashier_cannot_create_cashier(cashier_client: APIClient) -> None:
    response = cashier_client.post(
        "/auth/cashiers",
        {"name": "Carol", "email": "carol@example.com", "password": "supersecret123"},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_unauthenticated_cannot_create_cashier(client: APIClient) -> None:
    response = client.post(
        "/auth/cashiers",
        {"name": "Dave", "email": "dave@example.com", "password": "supersecret123"},
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_owner_cannot_create_cashier_with_duplicate_email(owner_client: APIClient) -> None:
    User.objects.create_user(email="erin@example.com", name="Erin", password="supersecret123")
    response = owner_client.post(
        "/auth/cashiers",
        {"name": "Erin", "email": "erin@example.com", "password": "supersecret123"},
        format="json",
    )
    assert response.status_code == 400
    assert "already exists" in str(response.json()["email"])


def _make_other_business_cashier() -> User:
    other_owner = User.objects.create_user(
        email="other-owner@example.com", name="Other", password="supersecret123"
    )
    other_business = Business.objects.create(name="Other shop", owner=other_owner)
    other_owner.business = other_business
    other_owner.save(update_fields=["business"])
    return User.objects.create_user(
        email="other-cashier@example.com",
        name="Other cashier",
        password="supersecret123",
        role=User.Role.CASHIER,
        email_verified=True,
        business=other_business,
    )


@pytest.mark.django_db
def test_owner_lists_only_own_cashiers(owner_client: APIClient, cashier: User) -> None:
    _make_other_business_cashier()

    response = owner_client.get("/auth/cashiers")

    assert response.status_code == 200
    body = response.json()
    assert [c["email"] for c in body] == [cashier.email]
    assert body[0]["role"] == "cashier"
    assert body[0]["business"] == str(cashier.business_id)
    assert "password" not in body[0]


@pytest.mark.django_db
def test_owner_gets_cashier_detail(owner_client: APIClient, cashier: User) -> None:
    response = owner_client.get(f"/auth/cashiers/{cashier.pk}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(cashier.pk)
    assert body["email"] == cashier.email
    assert body["role"] == "cashier"


@pytest.mark.django_db
def test_owner_patches_cashier(owner_client: APIClient, cashier: User) -> None:
    response = owner_client.patch(
        f"/auth/cashiers/{cashier.pk}",
        {"name": "Bob le caissier", "phone": "+25770000099"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Bob le caissier"
    assert body["phone"] == "+25770000099"
    assert body["email"] == cashier.email
    cashier.refresh_from_db()
    assert cashier.name == "Bob le caissier"
    assert cashier.phone == "+25770000099"


@pytest.mark.django_db
def test_owner_puts_cashier(owner_client: APIClient, cashier: User) -> None:
    response = owner_client.put(
        f"/auth/cashiers/{cashier.pk}",
        {"name": "Carol", "email": cashier.email, "phone": "+25772222222"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Carol"
    assert body["phone"] == "+25772222222"
    cashier.refresh_from_db()
    assert cashier.name == "Carol"
    assert cashier.check_password("supersecret123")


@pytest.mark.django_db
def test_owner_updates_cashier_password(owner_client: APIClient, cashier: User) -> None:
    response = owner_client.patch(
        f"/auth/cashiers/{cashier.pk}", {"password": "newpassword123"}, format="json"
    )

    assert response.status_code == 200
    assert "password" not in response.json()
    cashier.refresh_from_db()
    assert cashier.check_password("newpassword123")


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_owner_changes_cashier_email_resends_verification(
    owner_client: APIClient, cashier: User
) -> None:
    response = owner_client.patch(
        f"/auth/cashiers/{cashier.pk}", {"email": "renewed@example.com"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["email_verified"] is False
    cashier.refresh_from_db()
    assert cashier.email == "renewed@example.com"
    assert cashier.email_verified is False
    assert cashier.email_verified_at is None
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_owner_cannot_update_cashier_to_duplicate_email(
    owner_client: APIClient, cashier: User
) -> None:
    User.objects.create_user(email="taken@example.com", name="T", password="supersecret123")

    response = owner_client.patch(
        f"/auth/cashiers/{cashier.pk}", {"email": "taken@example.com"}, format="json"
    )

    assert response.status_code == 400
    assert "already exists" in str(response.json()["email"])


@pytest.mark.django_db
def test_owner_cannot_change_cashier_role_or_business(
    owner_client: APIClient, cashier: User
) -> None:
    response = owner_client.patch(
        f"/auth/cashiers/{cashier.pk}", {"role": "owner", "business": "hijacked"}, format="json"
    )

    assert response.status_code == 200
    cashier.refresh_from_db()
    assert cashier.role == User.Role.CASHIER
    assert cashier.business_id is not None


@pytest.mark.django_db
def test_owner_deletes_cashier(owner_client: APIClient, cashier: User) -> None:
    response = owner_client.delete(f"/auth/cashiers/{cashier.pk}")

    assert response.status_code == 204
    assert not User.objects.filter(pk=cashier.pk).exists()


@pytest.mark.django_db
def test_owner_cannot_manage_other_business_cashier(owner_client: APIClient) -> None:
    other_cashier = _make_other_business_cashier()

    assert owner_client.get(f"/auth/cashiers/{other_cashier.pk}").status_code == 404
    assert (
        owner_client.patch(
            f"/auth/cashiers/{other_cashier.pk}", {"name": "Hijack"}, format="json"
        ).status_code
        == 404
    )
    assert owner_client.delete(f"/auth/cashiers/{other_cashier.pk}").status_code == 404
    other_cashier.refresh_from_db()
    assert other_cashier.name == "Other cashier"


@pytest.mark.django_db
def test_owner_cannot_manage_own_account_via_cashier_endpoint(
    owner_client: APIClient, owner: User
) -> None:
    assert (
        owner_client.patch(
            f"/auth/cashiers/{owner.pk}", {"name": "Admin"}, format="json"
        ).status_code
        == 404
    )
    assert owner_client.delete(f"/auth/cashiers/{owner.pk}").status_code == 404


@pytest.mark.django_db
def test_cashier_cannot_read_or_manage_cashiers(cashier_client: APIClient, cashier: User) -> None:
    assert cashier_client.get("/auth/cashiers").status_code == 403
    assert cashier_client.get(f"/auth/cashiers/{cashier.pk}").status_code == 403
    assert (
        cashier_client.patch(
            f"/auth/cashiers/{cashier.pk}", {"name": "X"}, format="json"
        ).status_code
        == 403
    )
    assert (
        cashier_client.put(
            f"/auth/cashiers/{cashier.pk}",
            {"name": "X", "email": cashier.email},
            format="json",
        ).status_code
        == 403
    )
    assert cashier_client.delete(f"/auth/cashiers/{cashier.pk}").status_code == 403


@pytest.mark.django_db
def test_unauthenticated_cannot_read_or_manage_cashiers(client: APIClient, cashier: User) -> None:
    assert client.get("/auth/cashiers").status_code == 401
    assert client.get(f"/auth/cashiers/{cashier.pk}").status_code == 401
    assert (
        client.patch(f"/auth/cashiers/{cashier.pk}", {"name": "X"}, format="json").status_code
        == 401
    )
    assert client.delete(f"/auth/cashiers/{cashier.pk}").status_code == 401
