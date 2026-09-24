"""Email verification via signed (expiring) link."""

import uuid

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.template.loader import render_to_string

SIGNER_SALT = "fobos-email-verification"


def build_verification_token(user_id: str | uuid.UUID) -> str:
    """Return a signed, timestamped token embedding the user id."""
    signer = TimestampSigner(salt=SIGNER_SALT)
    return signer.sign_object(str(user_id))


def verify_verification_token(token: str) -> str | None:
    """Return the user id (UUID string) if the token is valid and not expired, else None."""
    signer = TimestampSigner(salt=SIGNER_SALT)
    try:
        user_id = signer.unsign_object(token, max_age=settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS)
        uuid.UUID(user_id)
        return str(user_id)
    except (BadSignature, SignatureExpired, ValueError):
        return None


def build_verification_url(user_id: str | uuid.UUID) -> str:
    token = build_verification_token(user_id)
    return f"{settings.APP_BASE_URL}/auth/verify-email/{token}/"


def send_verification_email(user_id: str | uuid.UUID, email: str) -> None:
    """Send the verification email — the signed URL only appears as the href of a button."""
    verify_url = build_verification_url(user_id)
    subject = render_to_string("accounts/emails/verify_email_subject.txt").strip()
    html = render_to_string("accounts/emails/verify_email.html", {"verify_url": verify_url})
    message = EmailMultiAlternatives(
        subject=subject,
        body="",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    message.attach_alternative(html, "text/html")
    message.send()
