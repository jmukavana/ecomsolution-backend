from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_optional_user
from app.models.auth import Session
from app.models.user import User
from app.schemas.cart import AddItemIn, CartOut, UpdateItemIn
from app.services.cart import (
    add_item,
    build_cart_view,
    clear_cart,
    get_or_create_cart,
    remove_item,
    update_item_qty,
)

router = APIRouter(prefix="/cart", tags=["cart"])


async def _resolve(
    request: Request,
    response: Response,
    db: AsyncSession,
    pair: tuple[Session, User] | None,
):
    user = pair[1] if pair else None
    return await get_or_create_cart(db, request=request, response=response, user=user)


@router.get("", response_model=CartOut)
async def get_cart(
    request: Request,
    response: Response,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    cart = await _resolve(request, response, db, pair)
    view = await build_cart_view(db, cart=cart)
    await db.commit()
    return view


@router.post("/items", response_model=CartOut, status_code=status.HTTP_201_CREATED)
async def post_item(
    payload: AddItemIn,
    request: Request,
    response: Response,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    cart = await _resolve(request, response, db, pair)
    await add_item(db, cart=cart, variant_id=payload.variant_id, qty=payload.qty)
    view = await build_cart_view(db, cart=cart)
    await db.commit()
    return view


@router.patch("/items/{item_id}", response_model=CartOut)
async def patch_item(
    item_id: int,
    payload: UpdateItemIn,
    request: Request,
    response: Response,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    cart = await _resolve(request, response, db, pair)
    await update_item_qty(db, cart=cart, item_id=item_id, qty=payload.qty)
    view = await build_cart_view(db, cart=cart)
    await db.commit()
    return view


@router.delete("/items/{item_id}", response_model=CartOut)
async def delete_item(
    item_id: int,
    request: Request,
    response: Response,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    cart = await _resolve(request, response, db, pair)
    await remove_item(db, cart=cart, item_id=item_id)
    view = await build_cart_view(db, cart=cart)
    await db.commit()
    return view


@router.post("/clear", response_model=CartOut)
async def post_clear(
    request: Request,
    response: Response,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    cart = await _resolve(request, response, db, pair)
    await clear_cart(db, cart=cart)
    view = await build_cart_view(db, cart=cart)
    await db.commit()
    return view
