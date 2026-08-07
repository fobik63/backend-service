#!/usr/bin/env python3
"""Tail PostgreSQL logs for auth failures → admin Dead Man's Switch (plan §37).

Watches a Postgres log file (or stdin) for password-authentication failures and
POSTs each match to the admin microservice. Crossing the fail threshold there
activates full external lockdown + Telegram.

Usage:
  python deploy/dead_mans_watchdog.py --log /var/log/postgresql/postgresql-16-main.log
  docker logs -f postgres 2>&1 | python deploy/dead_mans_watchdog.py --stdin

Requires ADMIN_PANEL_TOKEN (adm.v1...) and ADMIN_PANEL_URL (default localhost:8100).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("dead_mans_watchdog")

_PATTERNS = (
    "password authentication failed",
    "authentication failed for user",
    "no pg_hba.conf entry",
)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def looks_like_auth_failure(line: str) -> bool:
    lowered = line.lower()
    return any(p in lowered for p in _PATTERNS)


def post_failure(
    *,
    admin_url: str,
    token: str,
    line: str,
    timeout: float,
) -> dict:
    url = admin_url.rstrip("/") + "/security/dead-mans-switch/db-auth-failure"
    body = json.dumps({"line": line[:4000]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def follow_file(path: Path):
    """Yield new lines from ``path`` (like ``tail -F``)."""

    while not path.exists():
        logger.warning("Waiting for log file %s", path)
        time.sleep(2)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if not line:
                time.sleep(0.25)
                if not path.exists():
                    logger.warning("Log rotated away; reopening")
                    break
                continue
            yield line.rstrip("\n")


def run(*, log_path: Path | None, use_stdin: bool, dry_run: bool) -> int:
    admin_url = _env("ADMIN_PANEL_URL", "http://127.0.0.1:8100")
    token = _env("ADMIN_PANEL_TOKEN") or _env("DEAD_MANS_WATCHDOG_TOKEN")
    timeout = float(_env("DEAD_MANS_WATCHDOG_TIMEOUT_SECONDS", "5") or "5")

    if not token and not dry_run:
        logger.error("ADMIN_PANEL_TOKEN (or DEAD_MANS_WATCHDOG_TOKEN) is required")
        return 2

    if use_stdin:
        stream = (line.rstrip("\n") for line in sys.stdin)
    elif log_path is not None:
        def stream():  # type: ignore[misc]
            while True:
                yield from follow_file(log_path)

        stream = stream()
    else:
        logger.error("Provide --log PATH or --stdin")
        return 2

    logger.info("Watching for Postgres auth failures → %s", admin_url)
    for line in stream:
        if not looks_like_auth_failure(line):
            continue
        logger.warning("Auth failure line: %s", line[:200])
        if dry_run:
            continue
        try:
            result = post_failure(
                admin_url=admin_url,
                token=token,
                line=line,
                timeout=timeout,
            )
            if result.get("active"):
                logger.critical(
                    "DEAD MAN'S SWITCH ACTIVE reason=%s",
                    result.get("reason"),
                )
        except urllib.error.HTTPError as exc:
            logger.error("Admin report failed: HTTP %s %s", exc.code, exc.read()[:200])
        except Exception:
            logger.exception("Admin report failed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, help="Postgres log file to tail")
    parser.add_argument("--stdin", action="store_true", help="Read lines from stdin")
    parser.add_argument("--dry-run", action="store_true", help="Detect only, do not POST")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return run(log_path=args.log, use_stdin=args.stdin, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
