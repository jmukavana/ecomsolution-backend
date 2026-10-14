"""User-scoped endpoints under /api/me/* — profile, addresses, orders,
notifications, sessions, security/MFA.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import notifications
from app.auth.sessions import revoke_session
from app.auth.totp import (
    confirm_enrolment,
    disable_mfa,
    generate_otpauth_uri,
    get_verified_factor,
    start_enrolment,
)
from app.db import get_db
from app.deps import current_session_and_user, current_user
from app.models.auth import Session
from app.models.order import Order
from app.models.user import Address, User
from app.schemas.auth import (
    MeOut,
    MfaStartOut,
    MfaVerifyIn,
    MfaVerifyOut,
    SessionOut,
)
from app.schemas.me import (
    AddressIn,
    AddressOut,
    MyNotificationOut,
    ProfileUpdateIn,
    UnreadCountOut,
)
from app.schemas.order import OrderSummaryOut

router = APIRouter(prefix="/me", tags=["me"])


# ---------- Profile ----------

async def _me_payload(db: AsyncSession, session: Session, user: User) -> dict:
    factor = await get_verified_factor(db, user_id=user.id)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "mfa_required": user.mfa_required,
        "mfa_passed": session.mfa_passed,
        "email_verified_at": user.email_verified_at,
        "has_mfa_factor": factor is not None,
    }


@router.patch("/profile", response_model=MeOut)
async def update_profile(
    payload: ProfileUpdateIn,
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    session, user = pair
    data = payload.model_dump(exclude_unset=True)
    if "full_name" in data:
        user.full_name = (data["full_name"] or "").strip() or None
    if "phone" in data:
        user.phone = (data["phone"] or "").strip() or None
    await db.commit()
    return await _me_payload(db, session, user)


# ---------- Addresses ----------

@router.get("/addresses", response_model=list[AddressOut])
async def list_addresses(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[Address]:
    stmt = (
        select(Address)
        .where(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _clear_other_defaults(db: AsyncSession, user_id: int, keep_id: int | None) -> None:
    stmt = update(Address).where(Address.user_id == user_id).values(is_default=False)
    if keep_id is not None:
        stmt = stmt.where(Address.id != keep_id)
    await db.execute(stmt)


@router.post("/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(
    payload: AddressIn,
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> Address:
    # First address is implicitly the default.
    existing = (await db.execute(
        select(Address.id).where(Address.user_id == user.id).limit(1)
    )).first()
    is_default = payload.is_default or existing is None
    address = Address(user_id=user.id, **payload.model_dump(exclude={"is_default"}), is_default=is_default)
    db.add(address)
    await db.flush()
    if is_default:
        await _clear_other_defaults(db, user.id, keep_id=address.id)
    await db.commit()
    await db.refresh(address)
    return address


@router.patch("/addresses/{address_id}", response_model=AddressOut)
async def update_address(
    address_id: int,
    payload: AddressIn,
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> Address:
    address = await db.get(Address, address_id)
    if address is None or address.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Address not found")
    for field, value in payload.model_dump().items():
        setattr(address, field, value)
    await db.flush()
    if address.is_default:
        await _clear_other_defaults(db, user.id, keep_id=address.id)
    await db.commit()
    await db.refresh(address)
    return address


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: int,
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    address = await db.get(Address, address_id)
    if address is None or address.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Address not found")
    was_default = address.is_default
    await db.delete(address)
    await db.flush()
    if was_default:
        # Promote the most recent remaining address to default.
        nxt = (await db.execute(
            select(Address).where(Address.user_id == user.id).order_by(Address.id.desc()).limit(1)
        )).scalar_one_or_none()
        if nxt is not None:
            nxt.is_default = True
    await db.commit()


# ---------- Orders ----------

@router.get("/orders", response_model=list[OrderSummaryOut])
async def list_my_orders(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    stmt = (
        select(Order)
        .where(Order.user_id == user.id)
        .order_by(Order.id.desc())
        .limit(limit)
        .options(selectinload(Order.items))
    )
    orders = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": o.id,
            "status": o.status,
            "payment_method": o.payment_method,
            "total": o.total,
            "item_count": sum(i.qty for i in o.items),
            "created_at": o.created_at,
        }
        for o in orders
    ]


# ---------- In-app notifications ----------

def _notification_payload(notif) -> dict:
    return {
        "id": notif.id,
        "type": notif.type,
        "title": notif.title,
        "body": notif.body,
        "payload": notif.payload,
        "is_read": notif.read_at is not None,
        "read_at": notif.read_at,
        "created_at": notif.created_at,
    }


@router.get("/notifications", response_model=list[MyNotificationOut])
async def list_my_notifications(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    rows = await notifications.list_for_user(db, user.id, limit=limit)
    return [_notification_payload(n) for n in rows]


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
async def my_unread_count(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"unread": await notifications.unread_count(db, user.id)}


@router.post("/notifications/read-all", response_model=UnreadCountOut)
async def read_all_notifications(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    await notifications.mark_all_read(db, user_id=user.id)
    await db.commit()
    return {"unread": 0}


@router.post("/notifications/{notification_id}/read", response_model=MyNotificationOut)
async def read_notification(
    notification_id: int,
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    notif = await notifications.mark_read(
        db, user_id=user.id, notification_id=notification_id
    )
    if notif is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    await db.commit()
    return _notification_payload(notif)


# ---------- Sessions ----------

@router.get("/sessions", response_model=list[SessionOut])
async def list_my_sessions(
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    session, user = pair
    stmt = (
        select(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .order_by(Session.last_seen_at.desc().nullslast(), Session.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "created_at": r.created_at,
            "last_seen_at": r.last_seen_at,
            "expires_at": r.expires_at,
            "current": r.id == session.id,
        }
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: int,
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    _session, user = pair
    row = await db.get(Session, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if row.revoked_at is not None:
        return
    await revoke_session(db, row)
    await db.commit()


# ---------- MFA enrolment ----------

@router.post("/security/mfa/start", response_model=MfaStartOut)
async def mfa_start(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await get_verified_factor(db, user_id=user.id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MFA already enabled. Disable it before re-enrolling.",
        )
    _factor, secret = await start_enrolment(db, user=user, label="Authenticator")
    await db.commit()
    return {
        "secret": secret,
        "otpauth_uri": generate_otpauth_uri(email=user.email, secret=secret),
    }


@router.post("/security/mfa/verify", response_model=MfaVerifyOut)
async def mfa_verify(
    payload: MfaVerifyIn,
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    session, user = pair
    recovery_codes = await confirm_enrolment(db, user=user, code=payload.code)
    # Successful enrolment also marks the current session as MFA-passed
    session.mfa_passed = True
    await db.commit()
    return {"verified": True, "recovery_codes": recovery_codes}


@router.delete("/security/mfa", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_disable(
    user: Annotated[User, Depends(current_user)],
    db: AsyncSession = Depends(get_db),
) -> None:
    if user.mfa_required:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "MFA is required for this account and cannot be disabled.",
        )
    await disable_mfa(db, user=user)
    await db.commit()

