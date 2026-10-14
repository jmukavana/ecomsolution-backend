from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.otp import consume_otp, issue_otp
from app.auth.sessions import (
    clear_session_cookies,
    create_session,
    resolve_session,
    revoke_session,
    set_session_cookies,
)
from app.auth.totp import get_verified_factor, verify_totp
from app.config import settings
from app.db import get_db
from app.deps import current_session_and_user
from app.models.auth import Session
from app.models.user import User
from app.notifications import dispatch_pending, enqueue
from app.schemas.auth import (
    MeOut,
    RequestOtpIn,
    RequestOtpOut,
    TotpStepUpIn,
    VerifyOtpIn,
    VerifyOtpOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-otp", response_model=RequestOtpOut)
async def request_otp(
    payload: RequestOtpIn,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> RequestOtpOut:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    user, code = await issue_otp(db, email=payload.email, ip=ip, user_agent=ua)
    await enqueue(
        db,
        key="auth.otp",
        payload={"name": user.full_name or "", "code": code, "ttl_minutes": settings.OTP_TTL_MINUTES},
        user_id=user.id,
        to_email=user.email,
    )
    await db.commit()
    background.add_task(dispatch_pending, limit=5)
    return RequestOtpOut(ttl_minutes=settings.OTP_TTL_MINUTES)


@router.post("/verify-otp", response_model=VerifyOtpOut)
async def verify_otp(
    payload: VerifyOtpIn,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> VerifyOtpOut:
    user = await consume_otp(db, email=payload.email, code=payload.code)
    needs_mfa = user.mfa_required and (
        await get_verified_factor(db, user_id=user.id)
    ) is not None

    # Detect a new device *before* creating this session (which records the UA).
    # Stay quiet on the very first sign-in — only alert returning users.
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    prior_user_agents = (
        await db.execute(select(Session.user_agent).where(Session.user_id == user.id))
    ).scalars().all()
    is_new_device = bool(prior_user_agents) and ua not in prior_user_agents

    _session, token = await create_session(
        db, user=user, mfa_passed=not needs_mfa, request=request
    )

    if is_new_device:
        await enqueue(
            db,
            key="auth.new_device",
            payload={
                "name": user.full_name or "",
                "ip": ip or "unknown",
                "user_agent": ua or "unknown",
                "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            },
            user_id=user.id,
            to_email=user.email,
        )

    set_session_cookies(response, sid_token=token)
    await db.commit()
    if is_new_device:
        background.add_task(dispatch_pending, limit=5)
    return VerifyOtpOut(next="mfa" if needs_mfa else "home")


@router.post("/verify-totp", response_model=VerifyOtpOut)
async def verify_totp_login(
    payload: TotpStepUpIn,
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
    db: AsyncSession = Depends(get_db),
) -> VerifyOtpOut:
    session, user = pair
    if session.mfa_passed:
        return VerifyOtpOut(next="home")
    ok = await verify_totp(db, user_id=user.id, code=payload.code)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid TOTP code")
    session.mfa_passed = True
    await db.commit()
    return VerifyOtpOut(next="home")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Response:
    sid = request.cookies.get(settings.SESSION_COOKIE_NAME)
    session = await resolve_session(db, sid=sid)
    if session is not None:
        await revoke_session(db, session)
        await db.commit()
    clear_session_cookies(response)
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
async def me(
    pair: Annotated[tuple[Session, User], Depends(current_session_and_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    session, user = pair
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

