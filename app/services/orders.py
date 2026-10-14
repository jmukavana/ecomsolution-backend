"""Orders service: transactional placement with variant-level stock decrement.

Concurrency:
- We `SELECT … FOR UPDATE` the product_variants rows for the variants being
  bought, in id order to avoid deadlocks.
- If any variant has insufficient stock, we 409 and the transaction rolls back.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants.counties import is_valid_county, normalise_phone_ke
from app.models.catalog import ProductVariant
from app.models.order import (
    Cart,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.models.user import User
from app.services.shipping import quote_shipping


async def quote_cart(
    db: AsyncSession, *, cart: Cart, county: str
) -> dict[str, Any]:
    """Quote subtotal + shipping for a cart without touching stock."""
    if not cart.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cart is empty")
    if not is_valid_county(county):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid county")

    variant_ids = [i.variant_id for i in cart.items]
    rows = (
        await db.execute(
            select(ProductVariant)
            .where(ProductVariant.id.in_(variant_ids))
            .options(selectinload(ProductVariant.product))
        )
    ).scalars().all()
    variants = {v.id: v for v in rows}

    subtotal = Decimal("0")
    weight = Decimal("0")
    for item in cart.items:
        v = variants.get(item.variant_id)
        if v is None:
            continue
        subtotal += (v.price_kes or Decimal("0")) * item.qty
        weight += (v.weight_kg or v.product.weight_kg or Decimal("0")) * item.qty

    quote = await quote_shipping(db, county=county, total_weight_kg=weight)
    total = subtotal + quote.cost
    return {
        "subtotal": str(subtotal.quantize(Decimal("0.01"))),
        "shipping": str(quote.cost.quantize(Decimal("0.01"))),
        "tax": "0.00",
        "total": str(total.quantize(Decimal("0.01"))),
        "eta_days": quote.eta_days,
        "county": county,
    }


async def place_order(
    db: AsyncSession,
    *,
    cart: Cart,
    user: User | None,
    payment_method: PaymentMethod,
    shipping_address: dict[str, Any],
    customer_email: str,
    customer_phone: str,
    customer_name: str | None,
) -> tuple[Order, Payment]:
    """Create order + decrement stock atomically. Returns (order, payment_row).

    `payment_method` decides downstream flow; this function does NOT call Daraja.
    For M-Pesa, callers invoke the STK Push and update the payment row.
    """
    if not cart.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cart is empty")

    county = shipping_address.get("county", "")
    if not is_valid_county(county):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid county")
    try:
        customer_phone = normalise_phone_ke(customer_phone)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    # Lock variant rows for the items we're decrementing
    variant_ids_sorted = sorted({i.variant_id for i in cart.items})
    rows = (
        await db.execute(
            select(ProductVariant)
            .where(ProductVariant.id.in_(variant_ids_sorted))
            .options(selectinload(ProductVariant.product))
            .with_for_update()
        )
    ).scalars().all()
    variants = {v.id: v for v in rows}

    # Validate stock
    for item in cart.items:
        v = variants.get(item.variant_id)
        if v is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"variant {item.variant_id} not found",
            )
        if v.stock < item.qty:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{v.product.name} — only {v.stock} in stock",
            )

    # Build totals
    subtotal = Decimal("0")
    weight = Decimal("0")
    for item in cart.items:
        v = variants[item.variant_id]
        subtotal += (v.price_kes or Decimal("0")) * item.qty
        weight += (v.weight_kg or v.product.weight_kg or Decimal("0")) * item.qty
    quote = await quote_shipping(db, county=county, total_weight_kg=weight)
    total = subtotal + quote.cost

    order = Order(
        user_id=user.id if user else None,
        customer_email=customer_email.strip().lower(),
        customer_phone=customer_phone,
        customer_name=customer_name,
        status=OrderStatus.PENDING,
        payment_method=payment_method,
        subtotal=subtotal,
        shipping=quote.cost,
        tax=Decimal("0"),
        total=total,
        shipping_address=shipping_address,
        items=[],
        payments=[],
    )
    db.add(order)
    await db.flush()

    for item in cart.items:
        v = variants[item.variant_id]
        v.stock -= item.qty  # row-locked above
        order.items.append(
            OrderItem(
                order_id=order.id,
                variant_id=v.id,
                qty=item.qty,
                unit_price=v.price_kes,
                product_name=v.product.name,
                sku=v.sku,
                options=v.option_values,
            )
        )

    payment = Payment(
        order_id=order.id,
        provider=payment_method,
        status=PaymentStatus.INITIATED,
        amount=total,
    )
    order.payments.append(payment)

    # Wipe the cart — order has taken ownership of these items now
    for item in list(cart.items):
        await db.delete(item)
    await db.flush()
    return order, payment


async def mark_order_paid(
    db: AsyncSession, *, order: Order, payment: Payment, receipt: str | None
) -> None:
    payment.status = PaymentStatus.SUCCESS
    if receipt:
        payment.mpesa_receipt = receipt
    order.status = OrderStatus.PAID
    await db.flush()


async def mark_payment_failed(
    db: AsyncSession,
    *,
    order: Order,
    payment: Payment,
    reason: str | None,
) -> None:
    payment.status = PaymentStatus.FAILED
    if reason:
        payment.raw_callback = {**(payment.raw_callback or {}), "failure_reason": reason}
    # Restock items
    for item in order.items:
        if item.variant_id is None:
            continue
        v = await db.get(ProductVariant, item.variant_id)
        if v is not None:
            v.stock += item.qty
    order.status = OrderStatus.CANCELLED
    await db.flush()
