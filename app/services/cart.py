"""Cart resolution: anonymous (cookie) OR user-bound.

A `cart_session` cookie carries an opaque token; hashed in the DB so a stolen
cookie can't be looked up via the value alone. Once a user logs in, future
cart calls bind to the user's cart and the cookie cart is merged + retired.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.crypto import hash_code, random_token
from app.config import settings
from app.models.catalog import Product, ProductVariant
from app.models.order import Cart, CartItem
from app.models.user import User

CART_COOKIE_NAME = "cart_session"


async def get_or_create_cart(
    db: AsyncSession,
    *,
    request: Request,
    response: Response | None,
    user: User | None,
) -> Cart:
    """Return the active cart for this caller, creating one if missing.

    - Logged-in user: cart bound by user_id. If a guest cart was present in the
      cookie, merge it into the user cart and clear the cookie.
    - Anonymous: identified by hashed `cart_session` cookie.
    """
    cookie_token = request.cookies.get(CART_COOKIE_NAME)

    if user is not None:
        user_cart = (
            await db.execute(
                select(Cart)
                .where(Cart.user_id == user.id)
                .options(selectinload(Cart.items))
            )
        ).scalar_one_or_none()
        if user_cart is None:
            user_cart = Cart(user_id=user.id, items=[])
            db.add(user_cart)
            await db.flush()

        if cookie_token:
            guest_cart = (
                await db.execute(
                    select(Cart)
                    .where(Cart.session_token_hash == hash_code(cookie_token))
                    .options(selectinload(Cart.items))
                )
            ).scalar_one_or_none()
            if guest_cart is not None and guest_cart.id != user_cart.id:
                await _merge_carts(db, src=guest_cart, dst=user_cart)
                if response is not None:
                    response.delete_cookie(CART_COOKIE_NAME, path="/")
        return user_cart

    # Anonymous path
    if cookie_token:
        cart = (
            await db.execute(
                select(Cart)
                .where(Cart.session_token_hash == hash_code(cookie_token))
                .options(selectinload(Cart.items))
            )
        ).scalar_one_or_none()
        if cart is not None:
            return cart

    token = random_token(24)
    cart = Cart(session_token_hash=hash_code(token), items=[])
    db.add(cart)
    await db.flush()
    if response is not None:
        response.set_cookie(
            CART_COOKIE_NAME,
            token,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            path="/",
        )
    return cart


async def _merge_carts(db: AsyncSession, *, src: Cart, dst: Cart) -> None:
    """Move items from src into dst, summing quantities when variants collide."""
    dst_index = {item.variant_id: item for item in dst.items}
    for item in list(src.items):
        existing = dst_index.get(item.variant_id)
        if existing is not None:
            existing.qty += item.qty
            await db.delete(item)
        else:
            item.cart_id = dst.id
    await db.flush()
    await db.delete(src)
    await db.flush()


async def add_item(
    db: AsyncSession, *, cart: Cart, variant_id: int, qty: int
) -> CartItem:
    if qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "qty must be > 0")
    variant = await db.get(ProductVariant, variant_id)
    if variant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "variant not found")
    if variant.stock < qty:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"only {variant.stock} in stock"
        )

    existing = next((i for i in cart.items if i.variant_id == variant_id), None)
    if existing is not None:
        new_qty = existing.qty + qty
        if variant.stock < new_qty:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"only {variant.stock} in stock (you already have {existing.qty})",
            )
        existing.qty = new_qty
        await db.flush()
        return existing

    item = CartItem(cart_id=cart.id, variant_id=variant_id, qty=qty)
    db.add(item)
    cart.items.append(item)
    await db.flush()
    return item


async def update_item_qty(
    db: AsyncSession, *, cart: Cart, item_id: int, qty: int
) -> CartItem:
    item = next((i for i in cart.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cart item not found")
    if qty <= 0:
        await db.delete(item)
        await db.flush()
        return item
    variant = await db.get(ProductVariant, item.variant_id)
    if variant is not None and variant.stock < qty:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"only {variant.stock} in stock"
        )
    item.qty = qty
    await db.flush()
    return item


async def remove_item(db: AsyncSession, *, cart: Cart, item_id: int) -> None:
    item = next((i for i in cart.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cart item not found")
    await db.delete(item)
    await db.flush()


async def clear_cart(db: AsyncSession, *, cart: Cart) -> None:
    for item in list(cart.items):
        await db.delete(item)
    await db.flush()


async def build_cart_view(db: AsyncSession, *, cart: Cart) -> dict[str, Any]:
    """Hydrate cart items with current product info + line totals."""
    if not cart.items:
        return {
            "id": cart.id,
            "items": [],
            "subtotal": "0.00",
            "total_weight_kg": "0.000",
            "item_count": 0,
        }

    variant_ids = [i.variant_id for i in cart.items]
    rows_stmt = (
        select(ProductVariant)
        .where(ProductVariant.id.in_(variant_ids))
        .options(selectinload(ProductVariant.product))
    )
    variants = {v.id: v for v in (await db.execute(rows_stmt)).scalars().all()}

    items: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    total_weight = Decimal("0")
    for item in cart.items:
        v = variants.get(item.variant_id)
        if v is None:
            continue
        product: Product = v.product
        line = (v.price_kes or Decimal("0")) * item.qty
        weight_each = v.weight_kg or product.weight_kg or Decimal("0")
        total_weight += weight_each * item.qty
        subtotal += line
        items.append(
            {
                "id": item.id,
                "variant_id": v.id,
                "sku": v.sku,
                "qty": item.qty,
                "unit_price": str(v.price_kes),
                "line_total": str(line),
                "stock": v.stock,
                "product": {
                    "id": product.id,
                    "slug": product.slug,
                    "name": product.name,
                    "brand": product.brand,
                    "image": (product.images[0]["url"]
                              if product.images else None),
                },
                "options": v.option_values,
            }
        )
    return {
        "id": cart.id,
        "items": items,
        "subtotal": str(subtotal.quantize(Decimal("0.01"))),
        "total_weight_kg": str(total_weight),
        "item_count": sum(i["qty"] for i in items),
    }
