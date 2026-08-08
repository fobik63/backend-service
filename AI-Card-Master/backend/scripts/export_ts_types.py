#!/usr/bin/env python3
"""Export OpenAPI schema + TypeScript types for the frontend.

Generates:
  - ``openapi.json`` — raw OpenAPI 3 schema from the FastAPI app
  - ``frontend_types.ts`` — TypeScript interfaces / type aliases derived from
    ``components.schemas`` (no external codegen dependency required)

Usage (from ``backend/``)::

    python -m scripts.export_ts_types
    python -m scripts.export_ts_types --out-dir ../frontend/src/api
    python -m scripts.export_ts_types --openapi-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

DEFAULT_OUT_DIR = _BACKEND_ROOT / "docs"
OPENAPI_NAME = "openapi.json"
TYPES_NAME = "frontend_types.ts"


def _load_openapi() -> dict[str, Any]:
    """Build OpenAPI from the FastAPI app without starting the server."""

    # Mirror tests/conftest.py safe defaults so export works without a .env.
    import os

    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/ai_card_master_export",
    )
    os.environ.setdefault("JWT_SECRET_KEY", "x" * 64)
    os.environ.setdefault("STABLE_DIFFUSION_API_KEY", "export-stability-key")
    os.environ.setdefault("MIDJOURNEY_PROVIDERS", "[]")
    os.environ.setdefault("MIDJOURNEY_CALLBACK_BASE_URL", "https://api.export.example")
    os.environ.setdefault(
        "MIDJOURNEY_WEBHOOK_TOKEN", "export-webhook-token-with-enough-entropy"
    )
    os.environ.setdefault(
        "MIDJOURNEY_REPLY_REF_SECRET", "export-reply-ref-secret-" + ("y" * 48)
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
    os.environ.setdefault("TELEGRAM_ERROR_LOGGING_ENABLED", "false")
    os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

    from app.main import app

    schema = app.openapi()
    if not isinstance(schema, dict):
        raise RuntimeError("FastAPI openapi() did not return a dict.")
    return schema


def _ts_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"Schema_{cleaned}"
    return cleaned or "AnonymousSchema"


def _ref_name(ref: str) -> str:
    # #/components/schemas/Foo → Foo
    return _ts_name(ref.rsplit("/", 1)[-1])


def _schema_to_ts(schema: dict[str, Any], *, schemas: dict[str, Any], indent: int = 0) -> str:
    """Best-effort OpenAPI schema → TypeScript type expression."""

    if "$ref" in schema:
        return _ref_name(str(schema["$ref"]))

    if "allOf" in schema and isinstance(schema["allOf"], list):
        parts = [
            _schema_to_ts(part, schemas=schemas, indent=indent)
            for part in schema["allOf"]
            if isinstance(part, dict)
        ]
        return " & ".join(parts) if parts else "unknown"

    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        parts = [
            _schema_to_ts(part, schemas=schemas, indent=indent)
            for part in schema["oneOf"]
            if isinstance(part, dict)
        ]
        return " | ".join(parts) if parts else "unknown"

    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        parts = [
            _schema_to_ts(part, schemas=schemas, indent=indent)
            for part in schema["anyOf"]
            if isinstance(part, dict)
        ]
        # Common FastAPI pattern: anyOf[T, null] → T | null
        return " | ".join(parts) if parts else "unknown"

    if "enum" in schema and isinstance(schema["enum"], list):
        literals = []
        for value in schema["enum"]:
            if isinstance(value, str):
                literals.append(json.dumps(value))
            elif value is None:
                literals.append("null")
            elif isinstance(value, bool):
                literals.append("true" if value else "false")
            else:
                literals.append(str(value))
        return " | ".join(literals) if literals else "never"

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        # OpenAPI 3.1 union types
        return " | ".join(
            _schema_to_ts({**schema, "type": t}, schemas=schemas, indent=indent)
            for t in schema_type
        )

    if schema_type == "string":
        fmt = schema.get("format")
        if fmt == "binary":
            return "string /* binary */"
        return "string"
    if schema_type == "integer":
        return "number"
    if schema_type == "number":
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            return f"Array<{_schema_to_ts(items, schemas=schemas, indent=indent)}>"
        return "Array<unknown>"

    if schema_type == "object" or "properties" in schema or schema.get("additionalProperties") is not None:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        pad = "  " * (indent + 1)
        closing = "  " * indent
        lines: list[str] = ["{"]
        if isinstance(props, dict):
            for key, prop_schema in props.items():
                if not isinstance(prop_schema, dict):
                    continue
                optional = "" if key in required else "?"
                safe_key = key if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) else json.dumps(key)
                ts_type = _schema_to_ts(prop_schema, schemas=schemas, indent=indent + 1)
                desc = prop_schema.get("description")
                if isinstance(desc, str) and desc.strip():
                    lines.append(f"{pad}/** {desc.strip().replace('*/', '* /')} */")
                lines.append(f"{pad}{safe_key}{optional}: {ts_type};")
        additional = schema.get("additionalProperties")
        if additional is True:
            lines.append(f"{pad}[key: string]: unknown;")
        elif isinstance(additional, dict):
            lines.append(
                f"{pad}[key: string]: {_schema_to_ts(additional, schemas=schemas, indent=indent + 1)};"
            )
        if len(lines) == 1:
            return "Record<string, unknown>"
        lines.append(f"{closing}}}")
        return "\n".join(lines)

    return "unknown"


def render_typescript(openapi: dict[str, Any]) -> str:
    """Render a single ``frontend_types.ts`` from OpenAPI components.schemas."""

    components = openapi.get("components") or {}
    schemas = components.get("schemas") or {}
    if not isinstance(schemas, dict):
        schemas = {}

    info = openapi.get("info") or {}
    title = info.get("title") or "AI-Card-Master API"
    version = info.get("version") or "0.0.0"

    lines: list[str] = [
        "/**",
        f" * Auto-generated TypeScript types for {title} v{version}.",
        " * DO NOT EDIT MANUALLY — regenerate via:",
        " *   python -m scripts.export_ts_types",
        " */",
        "",
        "/* eslint-disable */",
        "/* tslint:disable */",
        "",
        "export type UUID = string;",
        "",
    ]

    for name in sorted(schemas.keys(), key=str):
        schema = schemas[name]
        if not isinstance(schema, dict):
            continue
        ts_name = _ts_name(str(name))
        description = schema.get("description")
        if isinstance(description, str) and description.strip():
            lines.append(f"/** {description.strip().replace('*/', '* /')} */")
        body = _schema_to_ts(schema, schemas=schemas, indent=0)
        # Prefer interface for plain objects; type alias otherwise.
        if body.startswith("{"):
            lines.append(f"export interface {ts_name} {body}")
        else:
            lines.append(f"export type {ts_name} = {body};")
        lines.append("")

    # Handy path map for discoverability (method + path → operationId).
    lines.append("/** OpenAPI path → HTTP method → operationId (when present). */")
    lines.append("export interface ApiRouteMap {")
    paths = openapi.get("paths") or {}
    if isinstance(paths, dict):
        for path, item in sorted(paths.items(), key=lambda kv: str(kv[0])):
            if not isinstance(item, dict):
                continue
            safe_path = json.dumps(str(path))
            lines.append(f"  {safe_path}: {{")
            for method, op in sorted(item.items(), key=lambda kv: str(kv[0])):
                if method.startswith("x-") or not isinstance(op, dict):
                    continue
                if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                    continue
                op_id = op.get("operationId") or f"{method}_{path}"
                lines.append(f"    {method}: {json.dumps(str(op_id))};")
            lines.append("  };")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--openapi-only",
        action="store_true",
        help="Write openapi.json only (skip frontend_types.ts)",
    )
    parser.add_argument(
        "--types-only",
        action="store_true",
        help="Write frontend_types.ts only (still needs schema in-memory)",
    )
    args = parser.parse_args(argv)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    openapi = _load_openapi()

    if not args.types_only:
        openapi_path = out_dir / OPENAPI_NAME
        openapi_path.write_text(
            json.dumps(openapi, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {openapi_path}")

    if not args.openapi_only:
        types_path = out_dir / TYPES_NAME
        types_path.write_text(render_typescript(openapi), encoding="utf-8")
        print(f"Wrote {types_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
