"""Server-side session cookies. Opaque token → hashed → session row."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import hash_code, random_token
from app.config import settings
from app.models.auth import Session
from app.models.user import User


def _cookie_kwargs(*, max_age_seconds: int | None) -> dict:
    return {
        "max_age": max_age_seconds,
        "expires": max_age_seconds,
        "path": "/",
        "domain": settings.COOKIE_DOMAIN or None,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
    }


async def create_session(
    db: AsyncSession,
    *,
    user: User,
    mfa_passed: bool,
    request: Request,
) -> tuple[Session, str]:
    """Create a Session row, return (row, plaintext token to put in cookie)."""
    token = random_token(32)
    session = Session(
        user_id=user.id,
        token_hash=hash_code(token),
        mfa_passed=mfa_passed,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:512] or None,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.SESSION_TTL_DAYS),
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()
    return session, token


def set_session_cookies(response: Response, *, sid_token: str) -> str:
    """Set sid (HttpOnly) and csrf (readable by JS). Returns the csrf value."""
    csrf = random_token(24)
    max_age = settings.SESSION_TTL_DAYS * 24 * 60 * 60
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        sid_token,
        httponly=True,
        **_cookie_kwargs(max_age_seconds=max_age),
    )
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf,
        httponly=False,  # JS must read this to mirror into X-CSRF-Token
        **_cookie_kwargs(max_age_seconds=max_age),
    )
    return csrf


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )
    response.delete_cookie(
        settings.CSRF_COOKIE_NAME,
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )


async def resolve_session(db: AsyncSession, *, sid: str | None) -> Session | None:
    if not sid:
        return None
    now = datetime.now(timezone.utc)
    stmt = (
        select(Session)
        .where(
            Session.token_hash == hash_code(sid),
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        return None
    session.last_seen_at = now
    await db.flush()
    return session


async def revoke_session(db: AsyncSession, session: Session) -> None:
    session.revoked_at = datetime.now(timezone.utc)
    await db.flush()
