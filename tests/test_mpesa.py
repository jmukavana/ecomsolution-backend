"""M-Pesa callback: idempotency, success path, failure path. The HTTP integration
itself is mocked out — we trust httpx + the parse function."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.integrations.mpesa import parse_callback
from app.models.order import (
    Cart,
    CartItem,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.services.orders import place_order

from tests.factories import make_product, seed_shipping


def _success_callback(checkout_id: str, amount: int, receipt: str = "RCT1") -> dict:
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "m",
                "CheckoutRequestID": checkout_id,
                "ResultCode": 0,
                "ResultDesc": "Success",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": amount},
                        {"Name": "MpesaReceiptNumber", "Value": receipt},
                        {"Name": "PhoneNumber", "Value": 254700000000},
                    ]
                },
            }
        }
    }


def _failure_callback(checkout_id: str, code: int = 1032, desc: str = "Cancelled") -> dict:
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "m",
                "CheckoutRequestID": checkout_id,
                "ResultCode": code,
                "ResultDesc": desc,
            }
        }
    }


def test_parse_callback_success_extracts_metadata():
    o = parse_callback(_success_callback("ws_CO_A", 1500, "ABC123"))
    assert o.success is True
    assert o.result_code == 0
    assert o.checkout_request_id == "ws_CO_A"
    assert o.amount == 1500
    assert o.mpesa_receipt == "ABC123"


def test_parse_callback_failure():
    o = parse_callback(_failure_callback("ws_CO_B"))
    assert o.success is False
    assert o.result_code == 1032


def test_parse_callback_missing_metadata_safe():
    o = parse_callback({"Body": {"stkCallback": {"ResultCode": 0, "CheckoutRequestID": "x"}}})
    assert o.amount is None
    assert o.mpesa_receipt is None


@pytest.mark.asyncio
async def test_callback_idempotent_marks_paid_once(client, db):
    """Two identical success callbacks must not double-mark or duplicate state."""
    await seed_shipping(db)
    prod = await make_product(db, slug="watch", name="Watch", stock=10, price="2000")

    cart = Cart(items=[CartItem(variant_id=prod.variants[0].id, qty=1)])
    db.add(cart)
    await db.flush()

    order, payment = await place_order(
        db, cart=cart, user=None,
        payment_method=PaymentMethod.MPESA,
        shipping_address={"full_name": "X", "county": "Nairobi", "town": "y", "phone": "0700000000"},
        customer_email="x@example.com", customer_phone="0700000000", customer_name="X",
    )
    payment.checkout_request_id = "ws_CO_idem"
    await db.commit()

    payload = _success_callback("ws_CO_idem", int(order.total))

    r1 = await client.post("/api/mpesa/callback", json=payload)
    r2 = await client.post("/api/mpesa/callback", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["ResultDesc"] == "duplicate"

    await db.refresh(order)
    await db.refresh(payment)
    assert order.status == OrderStatus.PAID
    assert payment.status == PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_callback_for_unknown_checkout_id_ignored(client):
    payload = _success_callback("ws_CO_does_not_exist", 100)
    r = await client.post("/api/mpesa/callback", json=payload)
    assert r.status_code == 200
    assert r.json()["ResultDesc"] in ("unknown", "ignored")


# unused-suppress
_ = (Order, Decimal)
