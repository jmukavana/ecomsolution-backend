"""OTP request + verify flow.

Rate limited per-IP and per-email. Codes hashed at rest. Single-use.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import hash_code, random_numeric, verify_code
from app.config import settings
from app.models.auth import AuthOtp, OtpPurpose
from app.models.user import User, UserRole


async def _ensure_rate_limit(
    db: AsyncSession, *, email: str, ip: str | None
) -> None:
    one_min_ago = datetime.now(timezone.utc) - timedelta(minutes=1)

    by_email = (
        await db.execute(
            select(func.count())
            .select_from(AuthOtp)
            .join(User, AuthOtp.user_id == User.id)
            .where(User.email == email, AuthOtp.created_at >= one_min_ago)
        )
    ).scalar_one()
    if by_email >= settings.OTP_RATE_LIMIT_PER_EMAIL_PER_MIN:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many codes requested for this email. Try again in a minute.",
        )

    if ip:
        by_ip = (
            await db.execute(
                select(func.count())
                .where(AuthOtp.ip == ip, AuthOtp.created_at >= one_min_ago)
            )
        ).scalar_one()
        if by_ip >= settings.OTP_RATE_LIMIT_PER_IP_PER_MIN:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many login codes from this IP. Try again in a minute.",
            )


async def get_or_create_user(db: AsyncSession, email: str) -> User:
    """Lookup user by email, creating a stub on first-seen."""
    normalized = email.strip().lower()
    user = (
        await db.execute(select(User).where(User.email == normalized))
    ).scalar_one_or_none()
    if user is not None:
        return user
    user = User(email=normalized, role=UserRole.CUSTOMER, is_active=True)
    db.add(user)
    await db.flush()
    return user


async def issue_otp(
    db: AsyncSession,
    *,
    email: str,
    purpose: OtpPurpose = OtpPurpose.LOGIN,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, str]:
    """Generate an OTP, store its hash, return (user, plaintext code).

    Caller is responsible for sending the code through the notifications subsystem.
    """
    await _ensure_rate_limit(db, email=email, ip=ip)
    user = await get_or_create_user(db, email)

    code = random_numeric(settings.OTP_LENGTH)
    otp = AuthOtp(
        user_id=user.id,
        code_hash=hash_code(code),
        purpose=purpose,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.OTP_TTL_MINUTES),
        attempts=0,
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(otp)
    await db.flush()
    return user, code


async def consume_otp(
    db: AsyncSession,
    *,
    email: str,
    code: str,
    purpose: OtpPurpose = OtpPurpose.LOGIN,
) -> User:
    """Verify the code; raise on failure; mark consumed; return the user."""
    normalized = email.strip().lower()
    user = (
        await db.execute(select(User).where(User.email == normalized))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    now = datetime.now(timezone.utc)
    stmt = (
        select(AuthOtp)
        .where(
            AuthOtp.user_id == user.id,
            AuthOtp.purpose == purpose,
            AuthOtp.consumed_at.is_(None),
            AuthOtp.expires_at > now,
        )
        .order_by(AuthOtp.id.desc())
        .limit(1)
    )
    otp = (await db.execute(stmt)).scalar_one_or_none()
    if otp is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code expired or not found")

    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Too many attempts. Request a new code."
        )

    if not verify_code(code, otp.code_hash):
        otp.attempts += 1
        await db.flush()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    otp.consumed_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now
    await db.flush()
    return user
