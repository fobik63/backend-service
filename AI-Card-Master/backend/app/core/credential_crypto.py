"""AES-256 credential encryption for per-user marketplace API keys.

Uses Fernet (AES-128-CBC + HMAC-SHA256 under the hood with a 256-bit key
material derived via SHA-256 from the configured secret).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class CredentialCryptoError(Exception):
    """Credential encryption or decryption failed."""


def _fernet_from_secret(secret: str) -> Fernet:
    normalized = secret.strip()
    if not normalized:
        raise CredentialCryptoError("Encryption secret is empty.")
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_credentials(payload: dict[str, str], *, secret: str) -> str:
    """Serialize and encrypt a credentials dict; return a URL-safe token."""

    if not payload:
        raise CredentialCryptoError("Credentials payload is empty.")
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return _fernet_from_secret(secret).encrypt(raw).decode("ascii")
    except (TypeError, ValueError) as exc:
        raise CredentialCryptoError("Credentials payload is not serializable.") from exc


def decrypt_credentials(ciphertext: str, *, secret: str) -> dict[str, str]:
    """Decrypt a Fernet token back into a string credentials dict."""

    try:
        raw = _fernet_from_secret(secret).decrypt(ciphertext.encode("ascii"))
        payload: Any = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise CredentialCryptoError("Stored credentials could not be decrypted.") from exc
    if not isinstance(payload, dict):
        raise CredentialCryptoError("Decrypted credentials payload is invalid.")
    cleaned: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CredentialCryptoError("Decrypted credentials contain non-string values.")
        cleaned[key] = value
    return cleaned
