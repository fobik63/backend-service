"""Signed opaque callback references for provider webhook correlation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from uuid import UUID

from app.core.config import get_settings


def create_reply_ref(*, job_id: UUID, slide_id: UUID, provider_name: str) -> str:
    """Create a tamper-evident correlation value safe for provider round-trips."""

    payload = json.dumps(
        {
            "j": str(job_id),
            "s": str(slide_id),
            "p": provider_name,
            "n": secrets.token_urlsafe(12),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(_reply_ref_secret(), encoded, hashlib.sha256).hexdigest()
    return f"{encoded.decode('ascii')}.{signature}"


def verify_reply_ref(reply_ref: str) -> bool:
    """Verify only authenticity; repository lookup remains the source of identity."""

    try:
        encoded, supplied_signature = reply_ref.rsplit(".", 1)
    except ValueError:
        return False
    expected = hmac.new(
        _reply_ref_secret(),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, supplied_signature)


def callback_token() -> str:
    """Return the secret token embedded in provider callback URLs."""

    return get_settings().midjourney_webhook_token.get_secret_value().strip()


def _reply_ref_secret() -> bytes:
    settings = get_settings()
    secret = settings.midjourney_reply_ref_secret.get_secret_value().strip()
    if not secret:
        secret = settings.midjourney_webhook_token.get_secret_value().strip()
    if not secret:
        raise RuntimeError(
            "MIDJOURNEY_REPLY_REF_SECRET or MIDJOURNEY_WEBHOOK_TOKEN must be configured."
        )
    return secret.encode("utf-8")
