"""Email transport. Switch via EMAIL_BACKEND env: 'console' (dev) or 'smtp'."""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.config import settings

log = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send(
        self, *, to: str, subject: str, html: str | None, text: str
    ) -> None: ...


class ConsoleEmailSender:
    """Print emails to stdout. Default in dev — see OTPs without hitting SMTP."""

    async def send(
        self, *, to: str, subject: str, html: str | None, text: str
    ) -> None:
        banner = "─" * 72
        msg = (
            f"\n{banner}\n"
            f"[EMAIL (console)]\n"
            f"  From:    {settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>\n"
            f"  To:      {to}\n"
            f"  Subject: {subject}\n"
            f"{banner}\n"
            f"{text}\n"
            f"{banner}\n"
        )
        # Use print so it always reaches stdout regardless of logging config
        print(msg, flush=True)


class SmtpEmailSender:
    """SMTPS via aiosmtplib. Reuses the EMTech bancassurance mail server config."""

    async def send(
        self, *, to: str, subject: str, html: str | None, text: str
    ) -> None:
        msg = EmailMessage()
        msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")

        await aiosmtplib.send(
            msg,
            hostname=settings.MAIL_HOST,
            port=settings.MAIL_PORT,
            username=settings.MAIL_USERNAME,
            password=settings.MAIL_PASSWORD,
            use_tls=settings.MAIL_USE_SSL,
            timeout=15,
        )


def get_email_sender() -> EmailSender:
    if settings.EMAIL_BACKEND == "smtp":
        if not settings.MAIL_PASSWORD:
            log.warning(
                "EMAIL_BACKEND=smtp but MAIL_PASSWORD is empty; emails will fail."
            )
        return SmtpEmailSender()
    return ConsoleEmailSender()
