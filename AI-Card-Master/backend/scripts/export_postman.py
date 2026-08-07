#!/usr/bin/env python3
"""Build a Postman Collection v2.1 (Bruno-importable) for auth flows.

Includes register / login / me requests with Postman test scripts that
assert status codes, response shapes, and persist JWT tokens into
collection variables for downstream authenticated calls.

Usage (from ``backend/``)::

    python -m scripts.export_postman
    python -m scripts.export_postman --out docs/postman_auth_collection.json
    python -m scripts.export_postman --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

DEFAULT_OUT = _BACKEND_ROOT / "docs" / "postman_auth_collection.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_EMAIL = "seed.pro@ai-card-master.local"
DEFAULT_PASSWORD = "SeedPass123!"
COLLECTION_NAME = "AI-Card-Master Auth"


def _pm_script(*lines: str) -> dict[str, Any]:
    return {"listen": "test", "script": {"type": "text/javascript", "exec": list(lines)}}


def _auth_session_assertions(*, expect_status: int, save_tokens: bool) -> dict[str, Any]:
    lines = [
        f"pm.test('HTTP {expect_status}', function () {{",
        f"    pm.response.to.have.status({expect_status});",
        "});",
        "const body = pm.response.json();",
        "pm.test('Auth session payload shape', function () {",
        "    pm.expect(body).to.have.property('user');",
        "    pm.expect(body).to.have.property('tokens');",
        "    pm.expect(body.user).to.include.keys(",
        "        'id', 'email', 'ai_coins', 'subscription_status', 'is_admin'",
        "    );",
        "    pm.expect(body.tokens).to.include.keys(",
        "        'access_token', 'refresh_token', 'token_type'",
        "    );",
        "    pm.expect(body.tokens.token_type).to.eql('bearer');",
        "    pm.expect(body.tokens.access_token).to.be.a('string').and.to.have.lengthOf.above(20);",
        "    pm.expect(body.tokens.refresh_token).to.be.a('string').and.to.have.lengthOf.above(20);",
        "});",
    ]
    if save_tokens:
        lines.extend(
            [
                "if (pm.response.code === " + str(expect_status) + ") {",
                "    pm.collectionVariables.set('access_token', body.tokens.access_token);",
                "    pm.collectionVariables.set('refresh_token', body.tokens.refresh_token);",
                "    pm.collectionVariables.set('user_id', body.user.id);",
                "    pm.collectionVariables.set('user_email', body.user.email);",
                "}",
            ]
        )
    return _pm_script(*lines)


def _me_assertions() -> dict[str, Any]:
    return _pm_script(
        "pm.test('HTTP 200', function () {",
        "    pm.response.to.have.status(200);",
        "});",
        "const body = pm.response.json();",
        "pm.test('Profile payload shape', function () {",
        "    pm.expect(body).to.include.keys(",
        "        'id', 'email', 'ai_coins', 'subscription_status', 'is_admin'",
        "    );",
        "    pm.expect(body.ai_coins).to.be.a('number');",
        "});",
        "pm.test('Bearer identity matches login email when set', function () {",
        "    const expected = pm.collectionVariables.get('user_email');",
        "    if (expected) { pm.expect(body.email).to.eql(expected); }",
        "});",
    )


def _url(path: str) -> dict[str, Any]:
    clean = path.lstrip("/")
    return {
        "raw": "{{base_url}}/" + clean,
        "host": ["{{base_url}}"],
        "path": clean.split("/"),
    }


def _json_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "raw",
        "raw": json.dumps(payload, ensure_ascii=False, indent=2),
        "options": {"raw": {"language": "json"}},
    }


def build_collection(*, base_url: str, email: str, password: str) -> dict[str, Any]:
    """Assemble a Postman Collection v2.1 document with auth auto-tests."""

    register_email = "postman.register.{{$timestamp}}@ai-card-master.local"

    return {
        "info": {
            "name": COLLECTION_NAME,
            "description": (
                "Auth contract pack for AI-Card-Master.\n\n"
                "Import into Postman or Bruno. Seed users from "
                "`python -m scripts.seed_db` work with the default login "
                f"credentials ({DEFAULT_EMAIL} / {DEFAULT_PASSWORD}).\n\n"
                "Tests auto-save `access_token` / `refresh_token` after "
                "register and login."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "base_url", "value": base_url},
            {"key": "access_token", "value": ""},
            {"key": "refresh_token", "value": ""},
            {"key": "user_id", "value": ""},
            {"key": "user_email", "value": email},
            {"key": "password", "value": password},
            {"key": "login_email", "value": email},
        ],
        "item": [
            {
                "name": "Auth",
                "item": [
                    {
                        "name": "Register",
                        "event": [
                            _auth_session_assertions(expect_status=201, save_tokens=True)
                        ],
                        "request": {
                            "method": "POST",
                            "header": [
                                {"key": "Content-Type", "value": "application/json"},
                                {
                                    "key": "Accept",
                                    "value": "application/json",
                                },
                            ],
                            "body": _json_body(
                                {
                                    "email": register_email,
                                    "password": "{{password}}",
                                }
                            ),
                            "url": _url("api/v1/auth/register"),
                            "description": (
                                "Creates a fresh account. Uses a timestamped "
                                "email so re-runs stay idempotent in CI."
                            ),
                        },
                        "response": [],
                    },
                    {
                        "name": "Login",
                        "event": [
                            _auth_session_assertions(expect_status=200, save_tokens=True)
                        ],
                        "request": {
                            "method": "POST",
                            "header": [
                                {"key": "Content-Type", "value": "application/json"},
                                {"key": "Accept", "value": "application/json"},
                            ],
                            "body": _json_body(
                                {
                                    "email": "{{login_email}}",
                                    "password": "{{password}}",
                                }
                            ),
                            "url": _url("api/v1/auth/login"),
                            "description": (
                                "Exchange credentials for JWT pair. Saves tokens "
                                "into collection variables."
                            ),
                        },
                        "response": [],
                    },
                    {
                        "name": "Login (bad password)",
                        "event": [
                            _pm_script(
                                "pm.test('HTTP 401', function () {",
                                "    pm.response.to.have.status(401);",
                                "});",
                                "pm.test('Error envelope', function () {",
                                "    const body = pm.response.json();",
                                "    pm.expect(body).to.have.property('detail');",
                                "});",
                            )
                        ],
                        "request": {
                            "method": "POST",
                            "header": [
                                {"key": "Content-Type", "value": "application/json"},
                                {"key": "Accept", "value": "application/json"},
                            ],
                            "body": _json_body(
                                {
                                    "email": "{{login_email}}",
                                    "password": "DefinitelyWrongPass!",
                                }
                            ),
                            "url": _url("api/v1/auth/login"),
                            "description": "Negative auth test: invalid credentials.",
                        },
                        "response": [],
                    },
                    {
                        "name": "Me",
                        "event": [_me_assertions()],
                        "request": {
                            "auth": {
                                "type": "bearer",
                                "bearer": [
                                    {
                                        "key": "token",
                                        "value": "{{access_token}}",
                                        "type": "string",
                                    }
                                ],
                            },
                            "method": "GET",
                            "header": [
                                {"key": "Accept", "value": "application/json"},
                            ],
                            "url": _url("api/v1/auth/me"),
                            "description": (
                                "Returns the authenticated profile. Requires "
                                "`access_token` from Register or Login."
                            ),
                        },
                        "response": [],
                    },
                    {
                        "name": "Me (missing token)",
                        "event": [
                            _pm_script(
                                "pm.test('HTTP 401', function () {",
                                "    pm.response.to.have.status(401);",
                                "});",
                            )
                        ],
                        "request": {
                            "auth": {"type": "noauth"},
                            "method": "GET",
                            "header": [
                                {"key": "Accept", "value": "application/json"},
                            ],
                            "url": _url("api/v1/auth/me"),
                            "description": "Negative auth test: no Authorization header.",
                        },
                        "response": [],
                    },
                    {
                        "name": "Balance (authenticated smoke)",
                        "event": [
                            _pm_script(
                                "pm.test('HTTP 200', function () {",
                                "    pm.response.to.have.status(200);",
                                "});",
                                "pm.test('Balance exposes ai_coins', function () {",
                                "    const body = pm.response.json();",
                                "    pm.expect(body).to.have.property('ai_coins');",
                                "    pm.expect(body.ai_coins).to.be.a('number');",
                                "});",
                            )
                        ],
                        "request": {
                            "auth": {
                                "type": "bearer",
                                "bearer": [
                                    {
                                        "key": "token",
                                        "value": "{{access_token}}",
                                        "type": "string",
                                    }
                                ],
                            },
                            "method": "GET",
                            "header": [
                                {"key": "Accept", "value": "application/json"},
                            ],
                            "url": _url("api/v1/payments/balance"),
                            "description": (
                                "Smoke check that the saved bearer token unlocks "
                                "a coin-balance endpoint used by the frontend."
                            ),
                        },
                        "response": [],
                    },
                ],
            }
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export Postman/Bruno auth collection with auto-tests.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL variable (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_EMAIL,
        help="Default login_email collection variable",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Default password collection variable",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    collection = build_collection(
        base_url=args.base_url.rstrip("/"),
        email=args.email,
        password=args.password,
    )
    out: Path = args.out
    if not out.is_absolute():
        out = (_BACKEND_ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote Postman collection: {out}")


if __name__ == "__main__":
    main()
