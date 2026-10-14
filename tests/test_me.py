"""Customer self-service endpoints: profile, addresses, orders, notifications.

These drive the ASGI app through the `client` fixture with a real session cookie,
so they exercise the cookie auth + CSRF middleware end to end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import hash_code, random_token
from app.models.auth import Session
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationStatus,
)
from app.models.order import Cart, CartItem, PaymentMethod
from app.models.user import User
from app.services.orders import place_order

from tests.factories import make_product, seed_shipping


async def _login(db: AsyncSession, email: str = "shopper@example.com") -> tuple[User, dict]:
    """Create a user + active session, return (user, cookies) for the client."""
    user = User(email=email, full_name="Test Shopper")
    db.add(user)
    await db.flush()
    token = random_token(32)
    csrf = random_token(24)
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_code(token),
            mfa_passed=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
            last_seen_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return user, {"sid": token, "csrf": csrf}


def _csrf_headers(cookies: dict) -> dict:
    return {"X-CSRF-Token": cookies["csrf"]}


@pytest.mark.asyncio
async def test_update_profile(db: AsyncSession, client: AsyncClient):
    _user, cookies = await _login(db)
    res = await client.patch(
        "/api/me/profile",
        json={"full_name": "New Name", "phone": "+254700000000"},
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["full_name"] == "New Name"
    assert body["phone"] == "+254700000000"


@pytest.mark.asyncio
async def test_address_crud_and_default_promotion(db: AsyncSession, client: AsyncClient):
    _user, cookies = await _login(db)

    # First address becomes default automatically.
    res = await client.post(
        "/api/me/addresses",
        json={"county": "Nairobi", "town": "Westlands", "phone": "0700000000"},
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.status_code == 201, res.text
    first = res.json()
    assert first["is_default"] is True

    # Second one marked default flips the first off.
    res = await client.post(
        "/api/me/addresses",
        json={"county": "Mombasa", "town": "Nyali", "phone": "0711111111", "is_default": True},
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.status_code == 201, res.text
    second = res.json()

    res = await client.get("/api/me/addresses", cookies=cookies)
    rows = {r["id"]: r for r in res.json()}
    assert rows[first["id"]]["is_default"] is False
    assert rows[second["id"]]["is_default"] is True

    # Deleting the default promotes the remaining address.
    res = await client.delete(
        f"/api/me/addresses/{second['id']}",
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.status_code == 204
    res = await client.get("/api/me/addresses", cookies=cookies)
    remaining = res.json()
    assert len(remaining) == 1
    assert remaining[0]["is_default"] is True


@pytest.mark.asyncio
async def test_list_my_orders_scoped_to_user(db: AsyncSession, client: AsyncClient):
    user, cookies = await _login(db)
    await seed_shipping(db)
    prod = await make_product(db, slug="tv", name="TV", price="30000", stock=5)
    cart = Cart(user_id=user.id, items=[CartItem(variant_id=prod.variants[0].id, qty=2)])
    db.add(cart)
    await db.flush()
    await place_order(
        db,
        cart=cart,
        user=user,
        payment_method=PaymentMethod.COD,
        shipping_address={"full_name": "X", "county": "Nairobi", "town": "y", "phone": "0700000000"},
        customer_email=user.email,
        customer_phone="0700000000",
        customer_name="X",
    )
    await db.commit()

    res = await client.get("/api/me/orders", cookies=cookies)
    assert res.status_code == 200, res.text
    orders = res.json()
    assert len(orders) == 1
    assert orders[0]["item_count"] == 2


@pytest.mark.asyncio
async def test_notifications_unread_count_and_mark_read(db: AsyncSession, client: AsyncClient):
    user, cookies = await _login(db)
    for body in ("Order placed", "Order shipped"):
        db.add(
            Notification(
                user_id=user.id,
                type="order.placed",
                channel=NotificationChannel.IN_APP,
                title="Update",
                body=body,
                status=NotificationStatus.SENT,
            )
        )
    await db.commit()

    res = await client.get("/api/me/notifications/unread-count", cookies=cookies)
    assert res.json()["unread"] == 2

    res = await client.get("/api/me/notifications", cookies=cookies)
    notifs = res.json()
    assert len(notifs) == 2
    assert all(n["is_read"] is False for n in notifs)

    # Mark one read → count drops to 1.
    res = await client.post(
        f"/api/me/notifications/{notifs[0]['id']}/read",
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.status_code == 200
    assert res.json()["is_read"] is True
    res = await client.get("/api/me/notifications/unread-count", cookies=cookies)
    assert res.json()["unread"] == 1

    # Read-all clears the rest.
    res = await client.post(
        "/api/me/notifications/read-all",
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.json()["unread"] == 0


@pytest.mark.asyncio
async def test_notifications_require_auth(client: AsyncClient):
    res = await client.get("/api/me/notifications")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_cannot_read_another_users_notification(db: AsyncSession, client: AsyncClient):
    _owner, _ = await _login(db, email="owner@example.com")
    other = Notification(
        user_id=_owner.id,
        type="order.placed",
        channel=NotificationChannel.IN_APP,
        body="secret",
        status=NotificationStatus.SENT,
    )
    db.add(other)
    await db.flush()
    notif_id = other.id

    _attacker, cookies = await _login(db, email="attacker@example.com")
    res = await client.post(
        f"/api/me/notifications/{notif_id}/read",
        cookies=cookies,
        headers=_csrf_headers(cookies),
    )
    assert res.status_code == 404
    await db.commit()
