"""CLI: mint an encrypted admin-panel token.

Usage (from backend/):
  python -m admin_microservice.mint_token --label ops --ttl-days 30
"""

from __future__ import annotations

import argparse
import sys

from app.core.admin_token import mint_admin_panel_token
from app.core.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mint AES-GCM admin panel token")
    parser.add_argument("--label", default="operator", help="Operator label stored in token")
    parser.add_argument("--ttl-days", type=int, default=30, help="Token lifetime in days")
    args = parser.parse_args(argv)

    settings = get_settings()
    secret = settings.effective_admin_panel_token_secret
    if len(secret) < 32:
        print("ADMIN_PANEL_TOKEN_SECRET (or JWT_SECRET_KEY) is too short.", file=sys.stderr)
        return 1

    token = mint_admin_panel_token(
        secret=secret,
        ttl_seconds=max(args.ttl_days, 1) * 24 * 3600,
        operator_label=args.label,
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
