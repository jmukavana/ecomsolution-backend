"""Template loading + Jinja2 rendering for notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationChannel, NotificationTemplate

# Sandboxed env protects against payload-side template injection (we won't render
# user-provided content as a template, but defense in depth is cheap).
_env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


@dataclass(slots=True)
class RenderedMessage:
    subject: str
    body: str


def render_template(
    template: NotificationTemplate, payload: dict[str, Any]
) -> RenderedMessage:
    subject = (
        _env.from_string(template.subject_template).render(**payload)
        if template.subject_template
        else ""
    )
    body = _env.from_string(template.body_template).render(**payload)
    return RenderedMessage(subject=subject, body=body)


async def load_templates(
    db: AsyncSession, key: str
) -> dict[NotificationChannel, NotificationTemplate]:
    """Return all active templates for a key, keyed by a channel."""
    stmt = select(NotificationTemplate).where(
        NotificationTemplate.key == key,
        NotificationTemplate.is_active.is_(True),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {row.channel: row for row in rows}
