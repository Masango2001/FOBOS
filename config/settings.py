"""
Django settings for the Commerce & Ledger backend.

All configuration is driven by environment variables (loaded from .env via
python-dotenv). The project runs exclusively through Docker; nothing here
assumes a local Python/PostgreSQL install.
"""

import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _required(name: str) -> str:
    """Return a non-empty env var or fail fast — no insecure fallback values."""
    value = os.getenv(name)
    if not value:
        raise ImproperlyConfigured(
            f"{name} is not set — provide it in .env.dev or .env.prod "
            "(copy .env.example and fill the values)."
        )
    return value


SECRET_KEY = _required("DJANGO_SECRET_KEY")
DEBUG = (os.getenv("DJANGO_DEBUG") or "False").lower() == "true"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ALLOWED_HOSTS = [
    host.strip()
    for host in (os.getenv("DJANGO_ALLOWED_HOSTS") or "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "corsheaders",
    "accounts",
    "products",
    "ledger",
    "sales",
    "subscriptions",
    "payments",
    "automation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _required("POSTGRES_DB"),
        "USER": _required("POSTGRES_USER"),
        "PASSWORD": _required("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST") or "db",
        "PORT": os.getenv("POSTGRES_PORT") or "5432",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "FOBOS Commerce & Ledger",
    "DESCRIPTION": (
        "Backend Commerce & Ledger de la Financial Operations Platform — "
        "produits, stock, ledger, automations et paiements (MVP)."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        # currency and settlement_currency share the same choice set — merge the
        # settlement enum into the single shared ledger.Currency enum.
        "SettlementCurrencyEnum": "ledger.models.Currency",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(os.getenv("JWT_ACCESS_HOURS") or "4")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS") or "7")),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Demo payment adapters (local stand-ins) enabled by default in dev so the full
# checkout→ledger chain runs without Backend Dev B's real adapters. Set to False
# (or in production) once the real BitLibera/Blink adapters are registered.
FOBOS_USE_DEMO_ADAPTERS = (
    os.getenv("FOBOS_USE_DEMO_ADAPTERS") or ("true" if DEBUG else "false")
).lower() == "true"
FOBOS_USE_LIVE_ADAPTERS = (os.getenv("FOBOS_USE_LIVE_ADAPTERS") or "false").lower() == "true"

# ---------------------------------------------------------------------------
# Provider credentials (doc §18, §47) — all OPTIONAL at startup: the demo
# adapters run without them and `integrations/` imports never read Django
# settings (they stay plain packages). The real clients fail fast with a typed
# error only when a protected provider call is made without configuration.
# ---------------------------------------------------------------------------
BLINK_API_URL = os.getenv("BLINK_API_URL") or ""
BLINK_API_KEY = os.getenv("BLINK_API_KEY") or ""
BLINK_USERNAME = os.getenv("BLINK_USERNAME") or ""
BLINK_BTC_WALLET_ID = os.getenv("BLINK_BTC_WALLET_ID") or ""
BLINK_USD_WALLET_ID = os.getenv("BLINK_USD_WALLET_ID") or ""
BLINK_LIGHTNING_ADDRESS = os.getenv("BLINK_LIGHTNING_ADDRESS") or ""
BLINK_WSS_URL = os.getenv("BLINK_WSS_URL") or "wss://ws.blink.sv/graphql"

BITLIBERA_BASE_URL = os.getenv("BITLIBERA_BASE_URL") or ""
BITLIBERA_MERCHANT_ID = os.getenv("BITLIBERA_MERCHANT_ID") or ""
BITLIBERA_API_KEY = os.getenv("BITLIBERA_API_KEY") or ""
YADIO_API_URL = os.getenv("YADIO_API_URL") or "https://api.yadio.io"
YADIO_RATE_CACHE_SECONDS = int(os.getenv("YADIO_RATE_CACHE_SECONDS") or "15")
YADIO_RATE_MAX_AGE_SECONDS = int(os.getenv("YADIO_RATE_MAX_AGE_SECONDS") or "300")

# Fixed company Lumicash number (doc §24/§47) — used as the settlement or
# debit-side recipient when the provider contract requires it. Per-customer
# Lumicash numbers are business data stored with the transaction, never here.
LUMICASH_PHONE = os.getenv("LUMICASH_PHONE") or ""

# Email verification link
EMAIL_VERIFICATION_MAX_AGE_SECONDS = int(
    os.getenv("EMAIL_VERIFICATION_MAX_AGE_SECONDS") or str(60 * 60 * 24)
)
APP_BASE_URL = os.getenv("APP_BASE_URL") or "http://localhost:8000"

# Email
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND") or "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST") or ""
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or "587")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER") or ""
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or ""
EMAIL_USE_TLS = (os.getenv("EMAIL_USE_TLS") or "True").lower() == "true"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or "fobos@example.com"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT") or BASE_DIR / "media")
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in (os.getenv("CORS_ALLOWED_ORIGINS") or "").split(",")
    if origin.strip()
]
CORS_ALLOW_ALL_ORIGINS = (os.getenv("CORS_ALLOW_ALL_ORIGINS") or "false").lower() == "true"

# Local file storage (Docker named volume `media`, mounted at /app/media).
# Product barcode images are persisted here — swap MEDIA_ROOT/DEFAULT_FILE_STORAGE
# for an object store (S3/MinIO) when the infra is provisioned.
MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
