"""Order placement: stock decrement, restock on cancel, attribute validation."""

from __future__ import annotations

import pytest
from decimal import Decimal
from fastapi import HTTPException

from app.models.catalog import Category, Product
from app.models.order import Cart, CartItem, OrderStatus, PaymentMethod
from app.services.catalog import validate_attributes
from app.services.orders import place_order

from tests.factories import make_attribute_set, make_product, seed_shipping


@pytest.mark.asyncio
async def test_place_order_decrements_stock(db):
    await seed_shipping(db)
    prod = await make_product(db, slug="laptop", name="Laptop", price="50000", stock=3)
    cart = Cart(items=[CartItem(variant_id=prod.variants[0].id, qty=2)])
    db.add(cart)
    await db.flush()

    order, payment = await place_order(
        db,
        cart=cart,
        user=None,
        payment_method=PaymentMethod.COD,
        shipping_address={
            "full_name": "X", "county": "Nairobi", "town": "y", "phone": "0700000000"
        },
        customer_email="x@example.com",
        customer_phone="0700000000",
        customer_name="X",
    )
    await db.commit()

    assert order.status == OrderStatus.PENDING
    assert payment.provider == PaymentMethod.COD
    assert order.total > Decimal("100000")  # subtotal + shipping
    await db.refresh(prod.variants[0])
    assert prod.variants[0].stock == 1  # 3 − 2


@pytest.mark.asyncio
async def test_place_order_rejects_insufficient_stock(db):
    await seed_shipping(db)
    prod = await make_product(db, slug="phone", name="Phone", price="20000", stock=1)
    cart = Cart(items=[CartItem(variant_id=prod.variants[0].id, qty=5)])
    db.add(cart)
    await db.flush()

    with pytest.raises(HTTPException) as ex:
        await place_order(
            db, cart=cart, user=None, payment_method=PaymentMethod.COD,
            shipping_address={"full_name": "X", "county": "Nairobi", "town": "y", "phone": "0700000000"},
            customer_email="x@example.com", customer_phone="0700000000", customer_name="X",
        )
    assert ex.value.status_code == 409
    await db.refresh(prod.variants[0])
    assert prod.variants[0].stock == 1  # unchanged


@pytest.mark.asyncio
async def test_place_order_rejects_invalid_county(db):
    prod = await make_product(db, slug="x", name="X", stock=1)
    cart = Cart(items=[CartItem(variant_id=prod.variants[0].id, qty=1)])
    db.add(cart)
    await db.flush()

    with pytest.raises(HTTPException) as ex:
        await place_order(
            db, cart=cart, user=None, payment_method=PaymentMethod.COD,
            shipping_address={"full_name": "X", "county": "Atlantis", "town": "y", "phone": "0700000000"},
            customer_email="x@example.com", customer_phone="0700000000", customer_name="X",
        )
    assert ex.value.status_code == 400
    assert "county" in ex.value.detail.lower()


@pytest.mark.asyncio
async def test_place_order_normalises_phone(db):
    await seed_shipping(db)
    prod = await make_product(db, slug="z", name="Z", stock=2)
    cart = Cart(items=[CartItem(variant_id=prod.variants[0].id, qty=1)])
    db.add(cart)
    await db.flush()

    order, _ = await place_order(
        db, cart=cart, user=None, payment_method=PaymentMethod.COD,
        shipping_address={"full_name": "X", "county": "Nairobi", "town": "y", "phone": "0712345678"},
        customer_email="x@example.com", customer_phone="0712345678", customer_name="X",
    )
    assert order.customer_phone == "+254712345678"


# ---------- Attribute validation ----------

@pytest.mark.asyncio
async def test_attribute_validation_requires_required_fields(db):
    s = await make_attribute_set(db, "X")
    with pytest.raises(HTTPException) as ex:
        validate_attributes({"condition": "new"}, list(s.attributes))
    assert ex.value.status_code == 422
    assert any("warranty_months" in err for err in ex.value.detail["attribute_errors"])


@pytest.mark.asyncio
async def test_attribute_validation_enum_options(db):
    s = await make_attribute_set(db, "Y")
    with pytest.raises(HTTPException) as ex:
        validate_attributes(
            {"warranty_months": 12, "condition": "broken"}, list(s.attributes)
        )
    assert ex.value.status_code == 422


@pytest.mark.asyncio
async def test_attribute_validation_accepts_clean(db):
    s = await make_attribute_set(db, "Z")
    out = validate_attributes(
        {"warranty_months": 24, "condition": "new"}, list(s.attributes)
    )
    assert out == {"warranty_months": 24, "condition": "new"}


@pytest.mark.asyncio
async def test_attribute_validation_rejects_unknown_keys(db):
    s = await make_attribute_set(db, "W")
    with pytest.raises(HTTPException):
        validate_attributes(
            {"warranty_months": 12, "condition": "new", "screen_size_xy": 99},
            list(s.attributes),
        )


# unused suppress
_ = (Product, Category)
