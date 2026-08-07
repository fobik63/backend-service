"""Request/input sanitization against SQL injection, XSS, and prompt-injection.

ORM bind parameters remain the primary SQL defense. This layer rejects
obvious attack payloads early and normalizes untrusted strings before they
reach LLM prompts or loosely typed handlers. Great Wall (plan §61) adds XSS
pattern detection used by middleware and JSON body sanitization.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Common SQL metacharacter / tautology probes (case-insensitive).
_SQL_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"(?:\bOR\b|\bAND\b)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+",
        r"\bUNION\b\s+(?:ALL\s+)?\bSELECT\b",
        r"\bDROP\b\s+\b(?:TABLE|DATABASE|SCHEMA)\b",
        r"\bINSERT\b\s+\bINTO\b",
        r"\bDELETE\b\s+\bFROM\b",
        r"\bUPDATE\b\s+\b\w+\b\s+\bSET\b",
        r"\bTRUNCATE\b\s+\bTABLE\b",
        r";\s*(?:DROP|DELETE|UPDATE|INSERT|ALTER|EXEC|EXECUTE)\b",
        r"--\s*$",
        r"/\*.*?\*/",
        r"\bEXEC(?:UTE)?\b\s*\(",
        r"xp_cmdshell",
        r"INFORMATION_SCHEMA\.",
        r"pg_sleep\s*\(",
        r"SLEEP\s*\(\s*\d+\s*\)",
        r"BENCHMARK\s*\(",
        r"LOAD_FILE\s*\(",
        r"INTO\s+(?:OUT|DUMP)FILE\b",
    )
)

# Reflected / stored XSS probes (HTML tags, event handlers, dangerous URIs).
_XSS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"<\s*script\b",
        r"</\s*script\s*>",
        r"javascript\s*:",
        r"vbscript\s*:",
        r"data\s*:\s*text/html",
        r"<\s*iframe\b",
        r"<\s*object\b",
        r"<\s*embed\b",
        r"<\s*svg\b[^>]*\bon\w+\s*=",
        r"<\s*img\b[^>]+on(?:error|load)\s*=",
        r"\bon(?:error|load|click|mouseover|focus|blur|submit|mouseenter|"
        r"mouseleave|keydown|keyup|change)\s*=",
        r"expression\s*\(",
        r"<\s*link\b[^>]+href\s*=",
        r"<\s*meta\b[^>]+http-equiv\s*=",
        r"&#x0*6[89]a?;",  # hex-encoded <script> starters
        r"&lt;\s*script",
    )
)

# Attempts to override / leak system prompts sent to LLMs.
_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
        r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts)",
        r"forget\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
        r"override\s+(?:the\s+)?system\s+prompt",
        r"you\s+are\s+now\s+(?:dan|jailbroken|unrestricted)",
        r"(?:system|developer)\s*:\s*",
        r"<\s*/?\s*system\s*>",
        r"\[(?:SYSTEM|INST|SYS)\]",
        r"reveal\s+(?:your\s+)?(?:system\s+)?prompt",
        r"print\s+(?:your\s+)?(?:system\s+)?prompt",
        r"show\s+(?:me\s+)?(?:the\s+)?hidden\s+instructions",
        r"do\s+not\s+follow\s+(?:the\s+)?(?:original|system)\s+rules",
        r"jailbreak\s+mode",
        r"DAN\s+mode",
        r"начинай\s+игнорировать\s+(?:предыдущие|системные)\s+инструкции",
        r"забудь\s+(?:все\s+)?(?:предыдущие|системные)\s+инструкции",
        r"покажи\s+(?:свой\s+)?системный\s+промпт",
        r"игнорируй\s+(?:все\s+)?(?:предыдущие|вышеуказанные)\s+инструкции",
    )
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_SCAN_DEPTH = 8
_MAX_STRING_LEN = 50_000


class InputSanitizationError(ValueError):
    """Raised when untrusted input fails safety checks."""

    def __init__(self, reason: str, *, category: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.category = category


def normalize_untrusted_text(value: str, *, max_length: int = _MAX_STRING_LEN) -> str:
    """NFKC-normalize, strip control characters, and bound length."""

    normalized = unicodedata.normalize("NFKC", value)
    cleaned = _CONTROL_CHARS_RE.sub("", normalized)
    if len(cleaned) > max_length:
        raise InputSanitizationError(
            f"Input exceeds maximum length of {max_length} characters.",
            category="length",
        )
    return cleaned


def detect_sql_injection(value: str) -> str | None:
    """Return a short category label when a SQL probe is detected."""

    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(value):
            return "sql_injection"
    return None


def detect_xss(value: str) -> str | None:
    """Return a short category label when an XSS probe is detected."""

    for pattern in _XSS_PATTERNS:
        if pattern.search(value):
            return "xss"
    return None


def detect_prompt_injection(value: str) -> str | None:
    """Return a short category label when a prompt-injection probe is detected."""

    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(value):
            return "prompt_injection"
    return None


def sanitize_text(
    value: str,
    *,
    check_sql: bool = True,
    check_xss: bool = True,
    check_prompt: bool = True,
    max_length: int = _MAX_STRING_LEN,
) -> str:
    """Normalize and optionally reject dangerous textual payloads."""

    cleaned = normalize_untrusted_text(value, max_length=max_length)
    if check_sql:
        hit = detect_sql_injection(cleaned)
        if hit is not None:
            raise InputSanitizationError(
                "Suspicious SQL-like payload rejected.",
                category=hit,
            )
    if check_xss:
        hit = detect_xss(cleaned)
        if hit is not None:
            raise InputSanitizationError(
                "Suspicious XSS payload rejected.",
                category=hit,
            )
    if check_prompt:
        hit = detect_prompt_injection(cleaned)
        if hit is not None:
            raise InputSanitizationError(
                "Prompt-injection attempt rejected.",
                category=hit,
            )
    return cleaned


def sanitize_payload(
    payload: Any,
    *,
    check_sql: bool = True,
    check_xss: bool = True,
    check_prompt: bool = True,
    depth: int = 0,
) -> Any:
    """Recursively sanitize string leaves inside JSON-compatible structures."""

    if depth > _MAX_SCAN_DEPTH:
        raise InputSanitizationError(
            "Payload nesting depth exceeds safety limit.",
            category="depth",
        )
    if isinstance(payload, str):
        return sanitize_text(
            payload,
            check_sql=check_sql,
            check_xss=check_xss,
            check_prompt=check_prompt,
        )
    if isinstance(payload, list):
        return [
            sanitize_payload(
                item,
                check_sql=check_sql,
                check_xss=check_xss,
                check_prompt=check_prompt,
                depth=depth + 1,
            )
            for item in payload
        ]
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                raise InputSanitizationError(
                    "JSON object keys must be strings.",
                    category="schema",
                )
            safe_key = sanitize_text(
                key,
                check_sql=check_sql,
                check_xss=check_xss,
                check_prompt=check_prompt,
                max_length=256,
            )
            cleaned[safe_key] = sanitize_payload(
                value,
                check_sql=check_sql,
                check_xss=check_xss,
                check_prompt=check_prompt,
                depth=depth + 1,
            )
        return cleaned
    return payload


def scan_text_for_threats(
    value: str,
    *,
    check_xss: bool = True,
) -> str | None:
    """Non-raising scanner used by middleware / scoring."""

    try:
        cleaned = normalize_untrusted_text(value)
    except InputSanitizationError as exc:
        return exc.category
    hit = detect_sql_injection(cleaned)
    if hit is not None:
        return hit
    if check_xss:
        hit = detect_xss(cleaned)
        if hit is not None:
            return hit
    return detect_prompt_injection(cleaned)
