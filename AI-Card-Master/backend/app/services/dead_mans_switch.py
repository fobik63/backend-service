"""Dead Man's Switch: DB password brute-force → lockdown + Telegram (plan §37).

When the admin panel (or host watchdog) observes repeated PostgreSQL
authentication failures, this service:

1. Marks a Redis lockdown flag consumed by ``DeadMansSwitchMiddleware``.
2. Optionally raises Cloudflare zone security to ``under_attack``.
3. Optionally runs a host firewall lockdown script (DROP external).
4. Sends an emergency Telegram alert to operators.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any

from redis.exceptions import RedisError

from app.core.client_ip import parse_trusted_proxy_cidrs
from app.core.config import Settings, get_settings
from app.infrastructure.cloudflare import get_cloudflare_client
from app.infrastructure.redis import get_security_redis_client
from app.services.telegram_alerts import send_operator_telegram

logger = logging.getLogger(__name__)

_DB_AUTH_FAIL_PATTERNS: tuple[str, ...] = (
    "password authentication failed",
    "authentication failed for user",
    "no pg_hba.conf entry",
    "fatal:  password authentication failed",
    " foreigndatawrapper  authentication failed",
)

_FAILURE_COUNTER_PREFIX = "security:db_auth_fail:"


@dataclass(frozen=True, slots=True)
class DeadMansSwitchState:
    """Persisted lockdown snapshot."""

    active: bool
    triggered_at: str | None = None
    reason: str | None = None
    source_ip: str | None = None
    fail_count: int = 0
    cloudflare_under_attack: bool = False
    host_lockdown: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def inactive(cls) -> DeadMansSwitchState:
        return cls(active=False)


@dataclass(frozen=True, slots=True)
class AuthFailureEvent:
    """Single observed PostgreSQL authentication failure."""

    source_ip: str
    raw_line: str
    user: str | None = None
    observed_at: str | None = None


def looks_like_db_auth_failure(line: str) -> bool:
    """Return True when a log/error line indicates Postgres auth brute-force."""

    lowered = line.lower()
    return any(pattern in lowered for pattern in _DB_AUTH_FAIL_PATTERNS)


def extract_source_ip(line: str) -> str:
    """Best-effort IPv4/IPv6 extraction from a Postgres log line."""

    # Typical: ... connection for user "x" from 203.0.113.9 port 54321 ...
    for token in line.replace(",", " ").replace("(", " ").replace(")", " ").split():
        candidate = token.strip()
        if candidate.lower().startswith("port"):
            continue
        try:
            parsed = ip_address(candidate)
            if not parsed.is_loopback:
                return str(parsed)
        except ValueError:
            continue
    return "unknown"


class DeadMansSwitchService:
    """Coordinate detection, Redis state, edge lockdown, and alerts."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._last_known_active = False

    @property
    def redis_key(self) -> str:
        return self._settings.dead_mans_switch_redis_key

    async def get_state(self) -> DeadMansSwitchState:
        try:
            raw = await get_security_redis_client().get(self.redis_key)
        except RedisError:
            logger.warning("Dead Man's Switch state read failed", exc_info=True)
            # Fail closed: if Redis blips after a real trigger we must not open
            # the public origin. Prefer the last known in-process flag when set.
            if getattr(self, "_last_known_active", False):
                return DeadMansSwitchState(
                    active=True,
                    reason="redis_read_failed_fail_closed",
                )
            return DeadMansSwitchState.inactive()
        if not raw:
            self._last_known_active = False
            return DeadMansSwitchState.inactive()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return DeadMansSwitchState.inactive()
        if not isinstance(payload, dict):
            return DeadMansSwitchState.inactive()
        state = DeadMansSwitchState(
            active=bool(payload.get("active")),
            triggered_at=payload.get("triggered_at"),
            reason=payload.get("reason"),
            source_ip=payload.get("source_ip"),
            fail_count=int(payload.get("fail_count") or 0),
            cloudflare_under_attack=bool(payload.get("cloudflare_under_attack")),
            host_lockdown=bool(payload.get("host_lockdown")),
        )
        self._last_known_active = state.active
        return state

    async def is_active(self) -> bool:
        state = await self.get_state()
        return state.active

    def peer_is_vpn_allowlisted(self, peer_ip: str | None) -> bool:
        """True when the immediate peer is on the configured VPN gateway CIDR."""

        if not peer_ip:
            return False
        networks = parse_trusted_proxy_cidrs(self._settings.vpn_gateway_cidrs)
        try:
            parsed = ip_address(peer_ip.strip())
        except ValueError:
            return False
        for network in networks:
            if parsed in network:  # type: ignore[operator]
                return True
        # Always allow loopback for local admin / health probes.
        return parsed.is_loopback

    async def record_auth_failure(self, event: AuthFailureEvent) -> DeadMansSwitchState:
        """Increment sliding-window counter; trigger lockdown when threshold hit."""

        if not self._settings.dead_mans_switch_enabled:
            return await self.get_state()

        current = await self.get_state()
        if current.active:
            return current

        window = max(1, self._settings.dead_mans_switch_window_seconds)
        threshold = max(1, self._settings.dead_mans_switch_fail_threshold)
        bucket = int(datetime.now(timezone.utc).timestamp()) // window
        counter_key = f"{_FAILURE_COUNTER_PREFIX}{event.source_ip}:{bucket}"

        try:
            client = get_security_redis_client()
            count = int(await client.incr(counter_key))
            await client.expire(counter_key, window * 2)
        except RedisError:
            logger.warning("Dead Man's Switch counter update failed", exc_info=True)
            # Fail closed on Redis errors once we already know it looks like auth abuse.
            count = threshold

        if count < threshold:
            logger.warning(
                "DB auth failure observed ip=%s count=%s/%s",
                event.source_ip,
                count,
                threshold,
            )
            return DeadMansSwitchState.inactive()

        reason = (
            f"PostgreSQL password brute-force detected: {count} failures "
            f"in {window}s from {event.source_ip}"
        )
        return await self.trigger(
            reason=reason,
            source_ip=event.source_ip,
            fail_count=count,
        )

    async def record_auth_failure_line(self, line: str) -> DeadMansSwitchState | None:
        """Parse a raw log line; return new state when it is an auth failure."""

        if not looks_like_db_auth_failure(line):
            return None
        event = AuthFailureEvent(
            source_ip=extract_source_ip(line),
            raw_line=line[:500],
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
        return await self.record_auth_failure(event)

    async def trigger(
        self,
        *,
        reason: str,
        source_ip: str = "unknown",
        fail_count: int = 0,
    ) -> DeadMansSwitchState:
        """Activate lockdown (idempotent if already active)."""

        existing = await self.get_state()
        if existing.active:
            return existing

        triggered_at = datetime.now(timezone.utc).isoformat()
        cf_ok = False
        if self._settings.dead_mans_switch_cloudflare_under_attack:
            cf_ok = await get_cloudflare_client().set_security_level("under_attack")

        host_ok = False
        if self._settings.dead_mans_switch_run_host_lockdown:
            host_ok = await self._run_host_script(
                self._settings.dead_mans_switch_lockdown_script
            )

        state = DeadMansSwitchState(
            active=True,
            triggered_at=triggered_at,
            reason=reason[:1000],
            source_ip=source_ip,
            fail_count=fail_count,
            cloudflare_under_attack=cf_ok,
            host_lockdown=host_ok,
        )
        await self._persist(state)
        await self._notify_telegram(state)
        logger.critical("DEAD MAN'S SWITCH ACTIVATED: %s", reason)
        return state

    async def clear(self, *, operator: str = "admin") -> DeadMansSwitchState:
        """Deactivate lockdown and restore Cloudflare security level to high."""

        previous = await self.get_state()
        if self._settings.dead_mans_switch_cloudflare_under_attack:
            await get_cloudflare_client().set_security_level("high")
        if previous.host_lockdown and self._settings.dead_mans_switch_run_host_lockdown:
            await self._run_host_script(self._settings.dead_mans_switch_unlock_script)

        state = DeadMansSwitchState.inactive()
        try:
            await get_security_redis_client().delete(self.redis_key)
        except RedisError:
            logger.warning("Failed to clear Dead Man's Switch Redis key", exc_info=True)

        await send_operator_telegram(
            "🟢 DEAD_MANS_SWITCH_CLEARED\n"
            f"operator: {operator}\n"
            f"previous_reason: {previous.reason or 'n/a'}"
        )
        logger.warning("Dead Man's Switch cleared by %s", operator)
        return state

    async def _persist(self, state: DeadMansSwitchState) -> None:
        try:
            await get_security_redis_client().set(
                self.redis_key,
                json.dumps(state.to_dict(), ensure_ascii=False),
            )
        except RedisError:
            logger.error("Failed to persist Dead Man's Switch state", exc_info=True)

    async def _notify_telegram(self, state: DeadMansSwitchState) -> None:
        message = (
            "🚨 DEAD_MANS_SWITCH_ACTIVATED\n"
            "All external connections are being blocked.\n"
            f"reason: {state.reason}\n"
            f"source_ip: {state.source_ip}\n"
            f"fail_count: {state.fail_count}\n"
            f"triggered_at: {state.triggered_at}\n"
            f"cloudflare_under_attack: {state.cloudflare_under_attack}\n"
            f"host_lockdown: {state.host_lockdown}\n"
            "Clear via admin panel /security/dead-mans-switch/clear "
            "(VPN only) after investigation."
        )
        await send_operator_telegram(message)

    async def _run_host_script(self, script_path: str) -> bool:
        path = script_path.strip()
        if not path:
            return False

        def _run() -> bool:
            try:
                completed = subprocess.run(
                    ["/bin/bash", path],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if completed.returncode != 0:
                    logger.error(
                        "Lockdown script %s failed rc=%s stderr=%s",
                        path,
                        completed.returncode,
                        (completed.stderr or "")[:500],
                    )
                    return False
                return True
            except (OSError, subprocess.SubprocessError):
                logger.exception("Lockdown script %s could not run", path)
                return False

        return await asyncio.to_thread(_run)


_service: DeadMansSwitchService | None = None


def get_dead_mans_switch() -> DeadMansSwitchService:
    global _service
    if _service is None:
        _service = DeadMansSwitchService()
    return _service
