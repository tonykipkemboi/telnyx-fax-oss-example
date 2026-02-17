import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


def _send_via_resend(settings: Settings, *, to_email: str, subject: str, body: str) -> bool:
    from_email = (settings.resend_from_email or settings.smtp_from_email or "").strip()
    if not from_email:
        logger.warning("email_send_failed provider=resend reason=missing_from_email")
        return False

    try:
        response = httpx.post(
            f"{settings.resend_api_base_url.rstrip('/')}/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
            timeout=10.0,
        )
    except Exception as exc:
        logger.warning("email_send_failed provider=resend to=%s reason=%s", to_email, exc)
        return False

    if response.status_code >= 300:
        logger.warning(
            "email_send_failed provider=resend to=%s status=%s body=%s",
            to_email,
            response.status_code,
            response.text[:200],
        )
        return False

    logger.info("email_sent provider=resend to=%s", to_email)
    return True


def _send_via_smtp(settings: Settings, *, to_email: str, subject: str, body: str) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
    except Exception as exc:
        logger.warning("email_send_failed provider=smtp to=%s reason=%s", to_email, exc)
        return False

    logger.info("email_sent provider=smtp to=%s", to_email)
    return True


def send_email(settings: Settings, *, to_email: str, subject: str, body: str) -> None:
    if settings.resend_api_key and _send_via_resend(
        settings,
        to_email=to_email,
        subject=subject,
        body=body,
    ):
        return

    if settings.smtp_host and _send_via_smtp(
        settings,
        to_email=to_email,
        subject=subject,
        body=body,
    ):
        return

    logger.info("email_not_configured to=%s subject=%s", to_email, subject)
