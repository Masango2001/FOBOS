"""Shared pytest fixtures for the whole FOBOS backend."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient


def _make_user(email: str, role: str, business=None, password: str = "supersecret123"):
    from accounts.models import User

    user = User.objects.create_user(
        email=email,
        name=role.title(),
        password=password,
        role=role,
        email_verified=True,
    )
    if business is not None:
        user.business = business
        user.save(update_fields=["business"])
    return user


@pytest.fixture(autouse=True)
def _demo_adapters_registered():
    """Register the local demo adapters so the full chain runs without Dev B's."""
    from payments.adapters import register_adapter, register_onramp_adapter
    from payments.demo import (
        DemoBitLiberaOfframpAdapter,
        DemoBitLiberaOnrampAdapter,
        DemoBlinkDirectAdapter,
    )

    register_adapter(DemoBitLiberaOfframpAdapter())
    register_adapter(DemoBlinkDirectAdapter())
    register_onramp_adapter(DemoBitLiberaOnrampAdapter())


@pytest.fixture(autouse=True)
def _isolated_media_root(tmp_path):
    """Keep product barcode images out of the real media volume during tests."""
    from django.test import override_settings

    with override_settings(MEDIA_ROOT=str(tmp_path / "media"), MEDIA_URL="media/"):
        yield


@pytest.fixture
def business(db):
    from accounts.models import Business

    return Business.objects.create(
        name="Chez Alice",
        category="Retail",
        owner=_make_user("alice@fobos.test", "owner"),
        settlement_preference=Business.SettlementPreference.BIF_LUMICASH,
        lumicash_number="+25770000001",
    )


@pytest.fixture
def owner(db, business):
    user = business.owner
    user.business = business
    user.save(update_fields=["business"])
    return user


@pytest.fixture
def cashier(db, business):
    return _make_user("cashier@fobos.test", "cashier", business=business)


@pytest.fixture
def auth_client():
    return APIClient()


@pytest.fixture
def owner_client(owner):
    from rest_framework_simplejwt.tokens import AccessToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(owner)}")
    return client


@pytest.fixture
def cashier_client(cashier):
    from rest_framework_simplejwt.tokens import AccessToken

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(cashier)}")
    return client


@pytest.fixture
def product(db, business):
    from products.models import Product

    return Product.objects.create(
        business=business,
        name="Soda",
        barcode="6161",
        unit_cost=100,
        unit_price=250,
        stock_qty=10,
        stock_threshold=5,
    )
