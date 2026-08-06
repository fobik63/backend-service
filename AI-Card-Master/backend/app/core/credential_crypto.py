"""AES-256-GCM credential encryption for per-user marketplace API keys.

New writes use AES-256-GCM with a SHA-256-derived 256-bit key.
Legacy Fernet tokens (AES-128-CBC + HMAC) remain decryptable for migration.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_AES256_PREFIX = "aes256gcm.v1."
_NONCE_BYTES = 12


class CredentialCryptoError(Exception):
    """Credential encryption or decryption failed."""


def _aes_key_from_secret(secret: str) -> bytes:
    normalized = secret.strip()
    if not normalized:
        raise CredentialCryptoError("Encryption secret is empty.")
    return hashlib.sha256(normalized.encode("utf-8")).digest()


def _fernet_from_secret(secret: str) -> Fernet:
    digest = _aes_key_from_secret(secret)
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(payload: dict[str, str], *, secret: str) -> str:
    """Serialize and encrypt a credentials dict with AES-256-GCM."""

    if not payload:
        raise CredentialCryptoError("Credentials payload is empty.")
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CredentialCryptoError("Credentials payload is not serializable.") from exc

    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_aes_key_from_secret(secret)).encrypt(nonce, raw, None)
    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{_AES256_PREFIX}{token}"


def decrypt_credentials(ciphertext: str, *, secret: str) -> dict[str, str]:
    """Decrypt AES-256-GCM or legacy Fernet ciphertext into a string dict."""

    if not ciphertext or not ciphertext.strip():
        raise CredentialCryptoError("Stored credentials ciphertext is empty.")

    normalized = ciphertext.strip()
    try:
        if normalized.startswith(_AES256_PREFIX):
            raw = _decrypt_aes256_gcm(normalized, secret=secret)
        else:
            raw = _fernet_from_secret(secret).decrypt(normalized.encode("ascii"))
        payload: Any = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError, CredentialCryptoError) as exc:
        raise CredentialCryptoError("Stored credentials could not be decrypted.") from exc

    if not isinstance(payload, dict):
        raise CredentialCryptoError("Decrypted credentials payload is invalid.")
    cleaned: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CredentialCryptoError("Decrypted credentials contain non-string values.")
        cleaned[key] = value
    return cleaned


def _decrypt_aes256_gcm(token: str, *, secret: str) -> bytes:
    encoded = token[len(_AES256_PREFIX) :]
    try:
        blob = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise CredentialCryptoError("AES-256 token is malformed.") from exc
    if len(blob) <= _NONCE_BYTES:
        raise CredentialCryptoError("AES-256 token is too short.")
    nonce, encrypted = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        return AESGCM(_aes_key_from_secret(secret)).decrypt(nonce, encrypted, None)
    except Exception as exc:  # noqa: BLE001 — AESGCM raises InvalidTag / ValueError
        raise CredentialCryptoError("AES-256 decryption failed.") from exc
