"""Enqueue notifications: render templates, create pending rows for each channel."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationStatus,
)
from app.models.user import User
from app.notifications.templates import load_templates, render_template

log = logging.getLogger(__name__)


async def enqueue(
    db: AsyncSession,
    *,
    key: str,
    payload: dict[str, Any],
    user_id: int | None = None,
    to_email: str | None = None,
) -> list[Notification]:
    """Create pending notification rows for every active channel of `key`.

    - `payload` is merged into the Jinja2 render context.
    - `to_email` is appended into the payload as `email` so templates / dispatcher can use it.
    - Returns the rows so callers (e.g. tests) can inspect them. Caller commits.
    """
    templates = await load_templates(db, key)
    if not templates:
        log.warning("notifications.enqueue: no active templates for key=%s", key)
        return []

    # Resolve email if not provided
    if to_email is None and user_id is not None:
        u = await db.get(User, user_id)
        if u is not None:
            to_email = u.email

    full_payload = {**payload, "email": to_email}
    rows: list[Notification] = []
    for channel, template in templates.items():
        rendered = render_template(template, full_payload)
        row = Notification(
            user_id=user_id,
            type=key,
            channel=channel,
            title=rendered.subject or None,
            body=rendered.body,
            payload=full_payload,
            status=NotificationStatus.PENDING,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


async def list_for_user(
    db: AsyncSession, user_id: int, limit: int = 50
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
        )
        .order_by(Notification.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def unread_count(db: AsyncSession, user_id: int) -> int:
    """Count of unread in-app notifications for the bell badge."""
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.read_at.is_(None),
        )
    )
    return int((await db.execute(stmt)).scalar_one())


async def mark_read(
    db: AsyncSession, *, user_id: int, notification_id: int
) -> Notification | None:
    """Mark one in-app notification read. Returns None if it isn't the user's."""
    notif = await db.get(Notification, notification_id)
    if (
        notif is None
        or notif.user_id != user_id
        or notif.channel != NotificationChannel.IN_APP
    ):
        return None
    if notif.read_at is None:
        notif.read_at = datetime.now(timezone.utc)
        notif.status = NotificationStatus.READ
    await db.flush()
    return notif


async def mark_all_read(db: AsyncSession, *, user_id: int) -> int:
    """Mark every unread in-app notification read. Returns the number affected."""
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc), status=NotificationStatus.READ)
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)
