"""Round-robin HTTP(S)/SOCKS proxy pool for marketplace mobile scrapes."""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProxyEndpoint:
    """One egress proxy URL accepted by httpx (`http://`, `https://`, `socks5://`)."""

    url: str

    def as_httpx_proxy(self) -> str:
        return self.url


class ProxyPool:
    """Thread-safe rotating proxy pool. Empty pool = direct egress."""

    def __init__(self, proxies: list[str] | tuple[str, ...] | None = None) -> None:
        cleaned: list[ProxyEndpoint] = []
        for raw in proxies or ():
            url = raw.strip()
            if not url:
                continue
            cleaned.append(ProxyEndpoint(url=url))
        self._proxies = tuple(cleaned)
        self._lock = Lock()
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None
        if self._proxies:
            logger.info("Stock parser proxy pool size=%s", len(self._proxies))
        else:
            logger.info("Stock parser proxy pool empty — direct egress")

    @property
    def size(self) -> int:
        return len(self._proxies)

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)

    def next(self) -> ProxyEndpoint | None:
        """Return the next proxy, or None when the pool is empty."""

        if self._cycle is None:
            return None
        with self._lock:
            return next(self._cycle)

    @classmethod
    def from_csv(cls, raw: str | None) -> "ProxyPool":
        """Parse `PROXY_URL_1,PROXY_URL_2` (comma/semicolon/newline separated)."""

        if not raw or not raw.strip():
            return cls(())
        parts = [
            chunk.strip()
            for chunk in raw.replace(";", ",").replace("\n", ",").split(",")
            if chunk.strip()
        ]
        return cls(parts)
