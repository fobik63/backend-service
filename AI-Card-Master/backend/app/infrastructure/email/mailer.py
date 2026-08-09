"""OTP email delivery via Resend API or SMTP (Gmail App Password supported).

Designed for FastAPI request handlers: prefer ``await run_in_threadpool(send_otp_email, …)``
so delivery failures surface as HTTP errors instead of silent BackgroundTasks.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from html import escape

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Outbound mail provider rejected or failed the send."""


def _mail_is_configured() -> bool:
    settings = get_settings()
    resend = settings.resend_api_key
    if resend is not None and resend.get_secret_value().strip():
        return True
    return bool((settings.smtp_host or "").strip())


def _ttl_minutes() -> int:
    settings = get_settings()
    ttl = max(60, int(settings.otp_ttl_seconds))
    return max(1, ttl // 60)


def _build_otp_html(*, brand: str, code: str) -> str:
    """Dark loft HTML template with inline SVG logo and large OTP."""

    safe_brand = escape(brand)
    safe_code = escape(code)
    minutes = _ttl_minutes()
    # Inline SVG: stacked cards mark (matches web CardLogoIcon).
    logo_svg = """\
<svg width="40" height="40" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="3.5" y="5" width="17" height="22" rx="2.5" stroke="#c2a68c" stroke-width="1.6" opacity="0.85"/>
  <rect x="7.5" y="1" width="17" height="22" rx="2.5" fill="#14171d" stroke="#10b981" stroke-width="1.6"/>
  <path d="M11 8.5h10M11 12.5h7M11 16.5h8.5" stroke="#c2a68c" stroke-width="1.4" stroke-linecap="round" opacity="0.75"/>
  <circle cx="21.5" cy="5.5" r="2" fill="#10b981"/>
</svg>"""

    return f"""\
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="color-scheme" content="dark"/>
  <title>{safe_brand} — код входа</title>
</head>
<body style="margin:0;padding:0;background:#0d0f12;color:#f3f4f6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0d0f12;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:440px;background:#14171d;border:1px solid rgba(194,166,140,0.28);border-radius:16px;overflow:hidden;">
          <tr>
            <td style="padding:28px 28px 8px 28px;">
              <table role="presentation" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="vertical-align:middle;padding-right:12px;">{logo_svg}</td>
                  <td style="vertical-align:middle;">
                    <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:18px;font-weight:700;letter-spacing:-0.02em;color:#f3f4f6;">
                      CARD AI<span style="display:inline-block;width:6px;height:6px;margin-left:4px;margin-bottom:8px;border-radius:999px;background:#10b981;"></span>
                    </div>
                    <div style="font-family:'Segoe UI',Arial,sans-serif;font-size:11px;letter-spacing:0.2em;text-transform:uppercase;color:#c2a68c;margin-top:2px;">
                      {safe_brand}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px 8px 28px;font-family:'Segoe UI',Arial,sans-serif;">
              <h1 style="margin:0 0 10px;font-size:22px;line-height:1.25;font-weight:650;color:#f9fafb;">
                Код для входа
              </h1>
              <p style="margin:0;font-size:14px;line-height:1.55;color:#9ca3af;">
                Введите этот код на сайте. Он действует {minutes}&nbsp;мин.
                Если вы не запрашивали вход — просто проигнорируйте письмо.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 28px 32px 28px;" align="center">
              <div style="display:inline-block;background:#0d0f12;border:1px solid rgba(16,185,129,0.35);border-radius:12px;padding:18px 28px;">
                <div style="font-family:ui-monospace,Consolas,'Courier New',monospace;font-size:36px;line-height:1;font-weight:700;letter-spacing:0.42em;color:#10b981;padding-left:0.42em;">
                  {safe_code}
                </div>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:0 28px 28px 28px;font-family:'Segoe UI',Arial,sans-serif;font-size:12px;line-height:1.5;color:#6b7280;border-top:1px solid rgba(255,255,255,0.06);">
              <p style="margin:18px 0 0;">Письмо отправлено автоматически. Не отвечайте на него.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _build_otp_text(*, brand: str, code: str) -> str:
    minutes = _ttl_minutes()
    return (
        f"Ваш одноразовый код для входа в {brand}:\n\n"
        f"    {code}\n\n"
        f"Код действует {minutes} мин. Если вы не запрашивали вход — "
        f"просто проигнорируйте это письмо.\n"
    )


def _build_otp_message(*, to_email: str, code: str) -> EmailMessage:
    settings = get_settings()
    brand = settings.service_display_name
    msg = EmailMessage()
    msg["Subject"] = f"{brand}: код входа"
    msg["From"] = settings.smtp_from_email or settings.support_email
    msg["To"] = to_email
    msg.set_content(_build_otp_text(brand=brand, code=code))
    msg.add_alternative(
        _build_otp_html(brand=brand, code=code),
        subtype="html",
    )
    return msg


def _send_via_resend(*, to_email: str, code: str) -> None:
    settings = get_settings()
    api_key = settings.resend_api_key
    if api_key is None:
        raise EmailDeliveryError("RESEND_API_KEY is not configured.")
    token = api_key.get_secret_value().strip()
    if not token:
        raise EmailDeliveryError("RESEND_API_KEY is empty.")

    from_email = settings.smtp_from_email or settings.support_email
    brand = settings.service_display_name
    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": f"{brand}: код входа",
        "text": _build_otp_text(brand=brand, code=code),
        "html": _build_otp_html(brand=brand, code=code),
    }
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15.0,
    )
    if response.status_code >= 400:
        raise EmailDeliveryError(
            f"Resend rejected send ({response.status_code}): {response.text[:200]}"
        )


def _send_via_smtp(*, to_email: str, code: str) -> None:
    settings = get_settings()
    host = (settings.smtp_host or "").strip()
    if not host:
        raise EmailDeliveryError("SMTP_HOST is not configured.")

    msg = _build_otp_message(to_email=to_email, code=code)
    port = int(settings.smtp_port)
    user = (settings.smtp_username or "").strip()
    password = (
        settings.smtp_password.get_secret_value()
        if settings.smtp_password is not None
        else ""
    )

    # Gmail: SMTP_HOST=smtp.gmail.com, port 587 + STARTTLS, or 465 + SSL + App Password.
    if settings.smtp_use_tls and port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if settings.smtp_use_tls:
            smtp.starttls()
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


def send_otp_email(to_email: str, code: str) -> None:
    """Send a 6-digit OTP email (sync). Raises ``EmailDeliveryError`` on failure.

    Provider priority: Resend → SMTP. No console / fake delivery stubs.
    """

    settings = get_settings()
    normalized = to_email.strip().lower()

    if not _mail_is_configured():
        raise EmailDeliveryError(
            "Email provider is not configured. Set RESEND_API_KEY or SMTP_* "
            "(e.g. Gmail smtp.gmail.com + App Password)."
        )

    try:
        if settings.resend_api_key is not None and settings.resend_api_key.get_secret_value().strip():
            _send_via_resend(to_email=normalized, code=code)
            logger.info("OTP email sent via Resend to %s", normalized)
            return

        _send_via_smtp(to_email=normalized, code=code)
        logger.info("OTP email sent via SMTP to %s", normalized)
    except EmailDeliveryError:
        raise
    except Exception as exc:
        logger.exception("OTP email delivery failed for %s", normalized)
        raise EmailDeliveryError(
            f"Failed to deliver OTP email: {exc}"
        ) from exc
