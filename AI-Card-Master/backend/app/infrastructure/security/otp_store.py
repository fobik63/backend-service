"""Redis-backed one-time password store for passwordless email login."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.core.config import get_settings
from app.infrastructure.redis import get_security_redis_client

logger = logging.getLogger(__name__)

OTP_KEY_PREFIX = "auth:otp:v1:"
OTP_META_PREFIX = "auth:otp:meta:v1:"
DEFAULT_TTL_SECONDS = 600
DEFAULT_CODE_LENGTH = 6
MAX_ATTEMPTS = 5


class OtpStoreUnavailableError(RuntimeError):
    """Security Redis unavailable for OTP operations."""


@dataclass(frozen=True, slots=True)
class OtpIssueResult:
    code: str
    ttl_seconds: int


class RedisOtpStore:
    """Hash-at-rest OTP codes with attempt limiting and TTL."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        code_length: int = DEFAULT_CODE_LENGTH,
    ) -> None:
        self._ttl = max(60, int(ttl_seconds))
        self._code_length = max(4, min(8, int(code_length)))

    def _pepper(self) -> bytes:
        settings = get_settings()
        secret = settings.jwt_secret_key.get_secret_value()
        return secret.encode("utf-8")

    def _hash_code(self, email: str, code: str) -> str:
        payload = f"{email.strip().lower()}:{code.strip()}".encode("utf-8")
        return hmac.new(self._pepper(), payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _key(email: str) -> str:
        return f"{OTP_KEY_PREFIX}{email.strip().lower()}"

    @staticmethod
    def _meta_key(email: str) -> str:
        return f"{OTP_META_PREFIX}{email.strip().lower()}"

    def generate_code(self) -> str:
        upper = 10**self._code_length
        return f"{secrets.randbelow(upper):0{self._code_length}d}"

    async def issue(self, email: str) -> OtpIssueResult:
        code = self.generate_code()
        digest = self._hash_code(email, code)
        key = self._key(email)
        meta = self._meta_key(email)
        try:
            client = get_security_redis_client()
            pipe = client.pipeline()
            pipe.set(key, digest, ex=self._ttl)
            pipe.set(meta, "0", ex=self._ttl)
            await pipe.execute()
        except RedisError as exc:
            logger.warning("OTP store issue failed: %s", exc)
            raise OtpStoreUnavailableError("OTP store unavailable") from exc
        return OtpIssueResult(code=code, ttl_seconds=self._ttl)

    async def verify_and_consume(self, email: str, code: str) -> bool:
        key = self._key(email)
        meta = self._meta_key(email)
        try:
            client = get_security_redis_client()
            stored = await client.get(key)
            if not stored:
                return False
            attempts_raw = await client.get(meta)
            attempts = int(attempts_raw or "0")
            if attempts >= MAX_ATTEMPTS:
                await client.delete(key, meta)
                return False
            expected = self._hash_code(email, code)
            if not hmac.compare_digest(stored, expected):
                await client.incr(meta)
                await client.expire(meta, self._ttl)
                return False
            await client.delete(key, meta)
            return True
        except RedisError as exc:
            logger.warning("OTP store verify failed: %s", exc)
            raise OtpStoreUnavailableError("OTP store unavailable") from exc
