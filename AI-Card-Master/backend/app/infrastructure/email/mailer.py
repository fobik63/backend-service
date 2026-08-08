"""OTP email delivery via Resend API or SMTP (aiosmtplib).

Designed for FastAPI ``BackgroundTasks``: callers schedule
``send_otp_email(to, code)`` without awaiting on the request path.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Outbound mail provider rejected or failed the send."""


def _build_otp_message(*, to_email: str, code: str) -> EmailMessage:
    settings = get_settings()
    brand = settings.service_display_name
    msg = EmailMessage()
    msg["Subject"] = f"{brand}: код входа {code}"
    msg["From"] = settings.smtp_from_email or settings.support_email
    msg["To"] = to_email
    msg.set_content(
        f"Ваш одноразовый код для входа в {brand}:\n\n"
        f"    {code}\n\n"
        f"Код действует 10 минут. Если вы не запрашивали вход — "
        f"просто проигнорируйте это письмо.\n"
    )
    msg.add_alternative(
        f"""\
<html>
  <body style="font-family:Segoe UI,Arial,sans-serif;background:#0f1115;color:#f3f4f6;padding:32px">
    <div style="max-width:420px;margin:0 auto;background:#16181e;border:1px solid rgba(194,166,140,0.3);border-radius:12px;padding:28px">
      <p style="margin:0 0 8px;font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:#c2a68c">{brand}</p>
      <h1 style="margin:0 0 16px;font-size:20px;color:#f3f4f6">Код для входа</h1>
      <p style="margin:0 0 20px;color:#9ca3af;font-size:14px">Введите этот код на сайте. Он действует 10 минут.</p>
      <p style="margin:0;text-align:center;font-size:32px;letter-spacing:0.35em;font-weight:700;color:#10b981">{code}</p>
    </div>
  </body>
</html>
""",
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
        "subject": f"{brand}: код входа {code}",
        "text": (
            f"Ваш одноразовый код для входа в {brand}: {code}. "
            "Код действует 10 минут."
        ),
        "html": (
            f"<p>Ваш код: <strong style='font-size:24px;letter-spacing:4px'>"
            f"{code}</strong></p><p>Действует 10 минут.</p>"
        ),
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
    """Send a 6-digit OTP email (sync; safe for BackgroundTasks).

    Provider priority: Resend → SMTP → development console log.
    """

    settings = get_settings()
    normalized = to_email.strip().lower()

    try:
        if settings.resend_api_key is not None and settings.resend_api_key.get_secret_value().strip():
            _send_via_resend(to_email=normalized, code=code)
            logger.info("OTP email sent via Resend to %s", normalized)
            return

        if (settings.smtp_host or "").strip():
            _send_via_smtp(to_email=normalized, code=code)
            logger.info("OTP email sent via SMTP to %s", normalized)
            return
    except Exception:
        logger.exception("OTP email delivery failed for %s", normalized)
        if settings.app_env == "production":
            raise
        # Non-production: fall through to console so local QA still works.
        logger.warning(
            "Falling back to console OTP for %s after delivery failure",
            normalized,
        )

    # Development / misconfigured mail: never block auth QA.
    logger.warning(
        "OTP email provider not configured — console OTP for %s: %s",
        normalized,
        code,
    )
