"""Load and render public legal documents (Terms / Privacy)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings

_LEGAL_DIR = Path(__file__).resolve().parent


class LegalDocumentNotFoundError(FileNotFoundError):
    """Requested markdown legal document is missing on disk."""


def _read_raw(filename: str) -> str:
    path = _LEGAL_DIR / filename
    if not path.is_file():
        raise LegalDocumentNotFoundError(f"Legal document not found: {filename}")
    return path.read_text(encoding="utf-8")


def _render(template: str, settings: Settings) -> str:
    replacements = {
        "{{SERVICE_NAME}}": settings.service_display_name,
        "{{OPERATOR_LEGAL_NAME}}": settings.legal_operator_name,
        "{{OPERATOR_ADDRESS}}": settings.legal_operator_address,
        "{{JURISDICTION}}": settings.legal_jurisdiction,
        "{{SUPPORT_EMAIL}}": settings.support_email,
        "{{PRIVACY_EMAIL}}": settings.privacy_email,
        "{{SITE_URL}}": settings.public_site_url.rstrip("/"),
        "{{EFFECTIVE_DATE}}": settings.legal_documents_effective_date,
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


@lru_cache(maxsize=1)
def _cached_terms_template() -> str:
    return _read_raw("terms_of_service.md")


@lru_cache(maxsize=1)
def _cached_privacy_template() -> str:
    return _read_raw("privacy_policy.md")


def get_terms_of_service(*, settings: Settings | None = None) -> str:
    """Return Terms of Service markdown with operator placeholders filled."""

    cfg = settings or get_settings()
    return _render(_cached_terms_template(), cfg)


def get_privacy_policy(*, settings: Settings | None = None) -> str:
    """Return Privacy Policy markdown with operator placeholders filled."""

    cfg = settings or get_settings()
    return _render(_cached_privacy_template(), cfg)
