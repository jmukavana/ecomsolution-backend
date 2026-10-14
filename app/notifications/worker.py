"""Dispatch pending notifications: email goes out via SMTP/console; in_app is delivered
the moment the row exists, so we only need to mark it sent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.integrations.email import get_email_sender
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationStatus,
)
from app.models.user import User

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


async def dispatch_one(db: AsyncSession, notif: Notification) -> None:
    notif.attempts += 1
    try:
        if notif.channel == NotificationChannel.EMAIL:
            await _send_email(db, notif)
        # in_app: nothing to do — it's "delivered" when the row exists
        notif.status = NotificationStatus.SENT
        notif.sent_at = datetime.now(timezone.utc)
        notif.last_error = None
    except Exception as e:  # noqa: BLE001 — we want any failure to mark+log
        log.exception("notification dispatch failed: id=%s key=%s", notif.id, notif.type)
        if notif.attempts >= MAX_ATTEMPTS:
            notif.status = NotificationStatus.FAILED
        notif.last_error = f"{type(e).__name__}: {e}"


async def _send_email(db: AsyncSession, notif: Notification) -> None:
    to = (notif.payload or {}).get("email") if notif.payload else None
    if not to and notif.user_id:
        u = await db.get(User, notif.user_id)
        if u is not None:
            to = u.email
    if not to:
        raise ValueError("no recipient email")

    sender = get_email_sender()
    await sender.send(
        to=str(to),
        subject=notif.title or "",
        text=notif.body,
        html=None,  # v1: plain text. HTML templates can come later.
    )


async def dispatch_pending(limit: int = 50) -> int:
    """One-shot dispatch run. Picks pending rows and processes them.

    Returns the number processed. Safe to call from FastAPI BackgroundTasks.
    """
    processed = 0
    async with SessionLocal() as db:
        stmt = (
            select(Notification)
            .where(Notification.status == NotificationStatus.PENDING)
            .order_by(Notification.id)
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        for row in rows:
            await dispatch_one(db, row)
            processed += 1
        await db.commit()
    return processed
