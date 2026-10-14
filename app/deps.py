"""FastAPI dependencies for cookie-based auth + role checks."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import resolve_session
from app.config import settings
from app.db import get_db
from app.models.auth import Session
from app.models.user import User, UserRole


async def get_optional_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    sid: Annotated[str | None, Cookie(alias="sid")] = None,
) -> tuple[Session, User] | None:
    session = await resolve_session(db, sid=sid)
    if session is None:
        return None
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return session, user


async def current_session_and_user(
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
) -> tuple[Session, User]:
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return pair


async def current_user(
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
) -> User:
    return pair[1]


async def current_session(
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
) -> Session:
    return pair[0]


async def require_mfa_passed(
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
) -> User:
    session, user = pair
    if user.mfa_required and not session.mfa_passed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "MFA verification required"
        )
    return user


async def require_admin(
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
) -> User:
    session, user = pair
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    if user.mfa_required and not session.mfa_passed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "MFA required for admin")
    return user


async def require_admin_or_bootstrap_token(
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> User | None:
    """Allow either an authenticated admin session OR the bootstrap ADMIN_TOKEN
    (used by CLI seed scripts and during initial admin bootstrap before MFA is set).
    """
    if pair is not None:
        session, user = pair
        if user.role == UserRole.ADMIN and (not user.mfa_required or session.mfa_passed):
            return user
    if x_admin_token and x_admin_token == settings.ADMIN_TOKEN:
        return None  # bootstrap path — no user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin authentication required")
