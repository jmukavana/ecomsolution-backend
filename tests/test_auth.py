"""OTP: hashing, TTL, attempts cap, single-use."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth.crypto import hash_code, random_numeric, verify_code
from app.auth.otp import consume_otp, issue_otp
from app.config import settings


def test_random_numeric_padded_to_length():
    for _ in range(20):
        assert len(random_numeric(6)) == 6


def test_hash_then_verify_roundtrips():
    code = "482917"
    h = hash_code(code)
    assert verify_code(code, h)
    assert not verify_code("000000", h)


@pytest.mark.asyncio
async def test_otp_issue_and_consume(db):
    user, code = await issue_otp(db, email="a@example.com", ip="127.0.0.1")
    await db.commit()
    assert len(code) == settings.OTP_LENGTH

    out = await consume_otp(db, email="a@example.com", code=code)
    assert out.id == user.id
    assert out.email_verified_at is not None


@pytest.mark.asyncio
async def test_otp_single_use(db):
    user, code = await issue_otp(db, email="b@example.com")
    await db.commit()
    await consume_otp(db, email="b@example.com", code=code)

    with pytest.raises(HTTPException) as ex:
        await consume_otp(db, email="b@example.com", code=code)
    assert ex.value.status_code == 400
    _ = user


@pytest.mark.asyncio
async def test_otp_wrong_code_increments_attempts(db):
    user, code = await issue_otp(db, email="c@example.com")
    await db.commit()

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        with pytest.raises(HTTPException):
            await consume_otp(db, email="c@example.com", code="000000")
        # consume_otp flushes attempts++ before raising; commit so it persists
        await db.commit()

    # Now even the correct code fails (attempts cap hit)
    with pytest.raises(HTTPException) as ex:
        await consume_otp(db, email="c@example.com", code=code)
    assert ex.value.status_code == 400
    _ = user


@pytest.mark.asyncio
async def test_otp_rate_limit_per_email(db):
    # The per-email limit defaults to 3/min; the 4th should fail
    for _ in range(settings.OTP_RATE_LIMIT_PER_EMAIL_PER_MIN):
        await issue_otp(db, email="d@example.com")
        await db.flush()

    with pytest.raises(HTTPException) as ex:
        await issue_otp(db, email="d@example.com")
    assert ex.value.status_code == 429


@pytest.mark.asyncio
async def test_new_device_alert_only_for_returning_user(db, client):
    """First sign-in is quiet; signing in from a new user-agent later alerts once."""
    from sqlalchemy import select

    from app.models.notification import (
        Notification,
        NotificationChannel,
        NotificationTemplate,
    )

    db.add(
        NotificationTemplate(
            key="auth.new_device",
            channel=NotificationChannel.IN_APP,
            subject_template="New sign-in detected",
            body_template="A new device signed in from {{ ip }} at {{ when }}.",
        )
    )
    await db.commit()

    async def _login(ua: str) -> None:
        _user, code = await issue_otp(db, email="dev@example.com")
        await db.commit()
        headers = {"user-agent": ua}
        # After the first login the client holds a csrf cookie; mirror it into the
        # header on later writes, exactly as the frontend api() wrapper does.
        csrf = client.cookies.get("csrf")
        if csrf:
            headers["X-CSRF-Token"] = csrf
        res = await client.post(
            "/api/auth/verify-otp",
            json={"email": "dev@example.com", "code": code},
            headers=headers,
        )
        assert res.status_code == 200, res.text

    await _login("Device-A")  # first ever sign-in → no alert
    alerts = (
        await db.execute(
            select(Notification).where(Notification.type == "auth.new_device")
        )
    ).scalars().all()
    assert alerts == []

    await _login("Device-B")  # new device for a returning user → one alert
    alerts = (
        await db.execute(
            select(Notification).where(Notification.type == "auth.new_device")
        )
    ).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].channel == NotificationChannel.IN_APP
