"""TOTP MFA + recovery codes."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import pyotp
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import (
    decrypt_secret,
    encrypt_secret,
    hash_code,
    random_token,
    verify_code,
)
from app.models.auth import MfaFactor, MfaFactorType, MfaRecoveryCode
from app.models.user import User


def generate_otpauth_uri(*, email: str, secret: str, issuer: str = "Ecomsolution") -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(email)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


async def start_enrolment(db: AsyncSession, *, user: User, label: str | None = None) -> tuple[MfaFactor, str]:
    """Create (or replace) an unverified TOTP factor; return (row, plaintext secret)."""
    existing_stmt = select(MfaFactor).where(
        MfaFactor.user_id == user.id, MfaFactor.type == MfaFactorType.TOTP
    )
    for row in (await db.execute(existing_stmt)).scalars().all():
        await db.delete(row)
    await db.flush()

    secret = pyotp.random_base32()
    factor = MfaFactor(
        user_id=user.id,
        type=MfaFactorType.TOTP,
        secret_encrypted=encrypt_secret(secret),
        label=label,
        verified_at=None,
    )
    db.add(factor)
    await db.flush()
    return factor, secret


async def get_verified_factor(db: AsyncSession, *, user_id: int) -> MfaFactor | None:
    stmt = select(MfaFactor).where(
        MfaFactor.user_id == user_id,
        MfaFactor.type == MfaFactorType.TOTP,
        MfaFactor.verified_at.is_not(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_pending_factor(db: AsyncSession, *, user_id: int) -> MfaFactor | None:
    stmt = select(MfaFactor).where(
        MfaFactor.user_id == user_id,
        MfaFactor.type == MfaFactorType.TOTP,
        MfaFactor.verified_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _verify_totp_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


async def verify_totp(db: AsyncSession, *, user_id: int, code: str) -> bool:
    """Try TOTP first, then recovery codes (which mark themselves consumed)."""
    factor = await get_verified_factor(db, user_id=user_id)
    if factor is not None:
        try:
            secret = decrypt_secret(factor.secret_encrypted)
        except Exception:
            return False
        if _verify_totp_code(secret, code):
            return True

    # Fall back to recovery codes
    stmt = select(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == user_id,
        MfaRecoveryCode.consumed_at.is_(None),
    )
    for rc in (await db.execute(stmt)).scalars().all():
        if verify_code(code.strip(), rc.code_hash):
            rc.consumed_at = datetime.now(timezone.utc)
            await db.flush()
            return True
    return False


async def confirm_enrolment(db: AsyncSession, *, user: User, code: str) -> list[str]:
    """Verify the user can produce a code from the unverified factor; mark verified;
    issue + return 10 fresh recovery codes (plaintext, shown ONCE).
    """
    factor = await get_pending_factor(db, user_id=user.id)
    if factor is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "MFA enrolment not started")
    try:
        secret = decrypt_secret(factor.secret_encrypted)
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "MFA secret unreadable") from e
    if not _verify_totp_code(secret, code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid TOTP code")

    factor.verified_at = datetime.now(timezone.utc)

    # Wipe any prior recovery codes for this user
    await db.execute(
        MfaRecoveryCode.__table__.delete().where(MfaRecoveryCode.user_id == user.id)
    )

    codes: list[str] = []
    for _ in range(10):
        code_plain = random_token(8).replace("_", "").replace("-", "")[:10]
        codes.append(code_plain)
        db.add(MfaRecoveryCode(user_id=user.id, code_hash=hash_code(code_plain)))
    await db.flush()
    return codes


async def disable_mfa(db: AsyncSession, *, user: User) -> None:
    await db.execute(
        MfaFactor.__table__.delete().where(MfaFactor.user_id == user.id)
    )
    await db.execute(
        MfaRecoveryCode.__table__.delete().where(MfaRecoveryCode.user_id == user.id)
    )
    await db.flush()
