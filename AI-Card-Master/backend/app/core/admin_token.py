"""Encrypted opaque tokens for the isolated admin microservice.

Tokens are AES-256-GCM sealed JSON claims (not end-user JWTs). They can only
be minted offline with ADMIN_PANEL_TOKEN_SECRET and verified by the admin API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_TOKEN_PREFIX = "adm.v1."
_NONCE_BYTES = 12
_DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class AdminTokenError(Exception):
    """Admin panel token minting or verification failed."""


@dataclass(frozen=True, slots=True)
class AdminTokenClaims:
    """Decrypted admin service token claims."""

    jti: str
    scope: str
    issued_at: int
    expires_at: int
    operator_label: str | None = None


def _key_from_secret(secret: str) -> bytes:
    normalized = secret.strip()
    if len(normalized) < 32:
        raise AdminTokenError(
            "ADMIN_PANEL_TOKEN_SECRET must contain at least 32 characters."
        )
    return hashlib.sha256(normalized.encode("utf-8")).digest()


def mint_admin_panel_token(
    *,
    secret: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    operator_label: str | None = None,
    scope: str = "admin_panel",
) -> str:
    """Create a new encrypted admin-panel bearer token."""

    if ttl_seconds <= 0:
        raise AdminTokenError("ttl_seconds must be positive.")
    now = int(time.time())
    payload: dict[str, Any] = {
        "jti": str(uuid4()),
        "scope": scope,
        "iat": now,
        "exp": now + ttl_seconds,
        "nonce": secrets.token_hex(8),
    }
    if operator_label:
        payload["operator_label"] = operator_label.strip()[:128]

    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key_from_secret(secret)).encrypt(nonce, raw, None)
    encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{_TOKEN_PREFIX}{encoded}"


def verify_admin_panel_token(
    token: str,
    *,
    secret: str,
    expected_scope: str = "admin_panel",
) -> AdminTokenClaims:
    """Decrypt and validate an admin-panel token."""

    if not token or not token.strip():
        raise AdminTokenError("Admin panel token is empty.")
    normalized = token.strip()
    if not normalized.startswith(_TOKEN_PREFIX):
        raise AdminTokenError("Admin panel token format is invalid.")

    encoded = normalized[len(_TOKEN_PREFIX) :]
    try:
        blob = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise AdminTokenError("Admin panel token is malformed.") from exc
    if len(blob) <= _NONCE_BYTES:
        raise AdminTokenError("Admin panel token is too short.")

    nonce, encrypted = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        raw = AESGCM(_key_from_secret(secret)).decrypt(nonce, encrypted, None)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — crypto/JSON failures
        raise AdminTokenError("Admin panel token could not be decrypted.") from exc

    if not isinstance(payload, dict):
        raise AdminTokenError("Admin panel token payload is invalid.")

    scope = str(payload.get("scope") or "").strip()
    if scope != expected_scope:
        raise AdminTokenError("Admin panel token scope is invalid.")

    try:
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
        jti = str(payload["jti"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise AdminTokenError("Admin panel token claims are incomplete.") from exc

    if not jti:
        raise AdminTokenError("Admin panel token jti is missing.")
    now = int(time.time())
    if expires_at <= now:
        raise AdminTokenError("Admin panel token has expired.")
    if issued_at > now + 60:
        raise AdminTokenError("Admin panel token issued_at is in the future.")

    operator_label = payload.get("operator_label")
    if operator_label is not None and not isinstance(operator_label, str):
        raise AdminTokenError("Admin panel token operator_label is invalid.")

    return AdminTokenClaims(
        jti=jti,
        scope=scope,
        issued_at=issued_at,
        expires_at=expires_at,
        operator_label=operator_label,
    )
