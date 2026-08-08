"""Outbound email adapters (SMTP / Resend)."""

from app.infrastructure.email.mailer import EmailDeliveryError, send_otp_email

__all__ = ["EmailDeliveryError", "send_otp_email"]
