import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_optional_user
from app.integrations.mpesa import MpesaError, initiate_stk_push, parse_callback
from app.models.auth import Session
from app.models.order import (
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.models.user import User
from app.notifications import dispatch_pending, enqueue
from app.schemas.order import (
    CheckoutIn,
    CheckoutOut,
    OrderOut,
    QuoteIn,
    QuoteOut,
)
from app.services.cart import build_cart_view, get_or_create_cart
from app.services.orders import (
    mark_order_paid,
    mark_payment_failed,
    place_order,
    quote_cart,
)

_ = mark_payment_failed  # reserved for future use (manual cancel path)

log = logging.getLogger(__name__)
router = APIRouter(tags=["checkout"])


@router.post("/cart/quote", response_model=QuoteOut)
async def post_quote(
    payload: QuoteIn,
    request: Request,
    response: Response,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = pair[1] if pair else None
    cart = await get_or_create_cart(db, request=request, response=response, user=user)
    q = await quote_cart(db, cart=cart, county=payload.county)
    await db.commit()
    return q


@router.post("/checkout", response_model=CheckoutOut)
async def post_checkout(
    payload: CheckoutIn,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = pair[1] if pair else None

    # Validate payment-method requirements BEFORE we touch the order/stock so a
    # config gap doesn't leave us trying to roll back a partial transaction.
    if payload.payment_method == "mpesa":
        from app.config import settings as _s
        if not (_s.MPESA_CONSUMER_KEY and _s.MPESA_CONSUMER_SECRET and _s.MPESA_PASSKEY):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "M-Pesa is not configured on this server. Use Cash on Delivery, or contact support.",
            )
        if not _s.MPESA_CALLBACK_URL:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "M-Pesa callback URL is not configured. Use Cash on Delivery, or contact support.",
            )

    cart = await get_or_create_cart(db, request=request, response=response, user=user)

    order, payment = await place_order(
        db,
        cart=cart,
        user=user,
        payment_method=PaymentMethod(payload.payment_method),
        shipping_address=payload.shipping_address.model_dump(),
        customer_email=payload.customer_email,
        customer_phone=payload.customer_phone,
        customer_name=payload.customer_name,
    )

    next_step: str
    customer_message: str | None = None

    if payment.provider == PaymentMethod.COD:
        # Cash on delivery: order stays pending, payment stays initiated until courier confirms.
        next_step = "cod_confirmation"
        # Mark provisional "processing" so admins can see actionable orders
        order.status = OrderStatus.PROCESSING
    else:
        # M-Pesa STK Push — if Daraja is unreachable, roll back the entire
        # checkout (no order, stock restored) so the user can retry cleanly.
        try:
            stk = await initiate_stk_push(
                phone=order.customer_phone,
                amount=int(order.total),
                account_ref=f"ECOM{order.id}",
                description=f"Order {order.id}",
            )
        except MpesaError as e:
            log.exception("M-Pesa STK push failed; rolling back")
            await db.rollback()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Couldn't reach M-Pesa: {e}",
            ) from e
        payment.checkout_request_id = stk.checkout_request_id
        next_step = "mpesa_prompt"
        customer_message = stk.customer_message or "Check your phone for the M-Pesa prompt."
        if stk.response_code != "0":
            # Daraja accepted but flagged — store and continue; user can retry.
            customer_message = stk.response_description or customer_message

    await enqueue(
        db,
        key="order.placed",
        payload={
            "order_id": order.id,
            "total": str(order.total),
            "payment_method": payment.provider.value,
        },
        user_id=order.user_id,
        to_email=order.customer_email,
    )
    await db.commit()
    background.add_task(dispatch_pending, limit=5)

    return {
        "order_id": order.id,
        "status": order.status,
        "payment_method": payment.provider,
        "total": str(order.total),
        "next": next_step,
        "checkout_request_id": payment.checkout_request_id,
        "customer_message": customer_message,
    }


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    pair: Annotated[tuple[Session, User] | None, Depends(get_optional_user)],
    db: AsyncSession = Depends(get_db),
) -> Order:
    user = pair[1] if pair else None
    order = await db.get(
        Order,
        order_id,
        options=[selectinload(Order.items), selectinload(Order.payments)],
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    # Allow if the order belongs to this user or there's no user attached yet
    # (guest orders are inspectable only by the immediate session — we'd add a
    # short-lived order_token cookie for that; keeping simple for v1).
    if user is None:
        if order.user_id is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "log in to view this order")
    elif order.user_id is not None and order.user_id != user.id and user.role.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your order")
    return order


# ----------------------- M-Pesa callback (CSRF-exempt) -----------------------

@router.post("/mpesa/callback", include_in_schema=False)
async def mpesa_callback(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Safaricom Daraja callback. Exempted from CSRF in middleware (no cookies).

    Idempotent on (checkout_request_id, status). If we've already processed it,
    return ok without re-mutating.
    """
    payload = await request.json()
    outcome = parse_callback(payload)
    log.info("M-Pesa callback: %s", outcome)

    if not outcome.checkout_request_id:
        # Daraja sometimes pings with malformed bodies during outages; ack and bail.
        return {"ResultCode": 0, "ResultDesc": "ignored"}

    stmt = (
        select(Payment)
        .where(Payment.checkout_request_id == outcome.checkout_request_id)
        .options(selectinload(Payment.order).selectinload(Order.items))
    )
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        log.warning("M-Pesa callback for unknown CheckoutRequestID=%s", outcome.checkout_request_id)
        return {"ResultCode": 0, "ResultDesc": "unknown"}

    # Idempotency — already terminal
    if payment.status in (PaymentStatus.SUCCESS, PaymentStatus.FAILED):
        return {"ResultCode": 0, "ResultDesc": "duplicate"}

    payment.raw_callback = payload
    order = payment.order
    if outcome.success:
        # Defence in depth: verify the amount matches the order total
        if outcome.amount is not None and int(outcome.amount) < int(order.total):
            log.warning(
                "M-Pesa callback amount %s < order total %s for order %s",
                outcome.amount, order.total, order.id,
            )
        await mark_order_paid(
            db, order=order, payment=payment, receipt=outcome.mpesa_receipt
        )
        await enqueue(
            db,
            key="order.paid",
            payload={
                "order_id": order.id,
                "total": str(order.total),
                "mpesa_receipt": outcome.mpesa_receipt,
            },
            user_id=order.user_id,
            to_email=order.customer_email,
        )
        background.add_task(dispatch_pending, limit=5)
    else:
        await mark_payment_failed(
            db, order=order, payment=payment, reason=outcome.result_desc
        )

    await db.commit()
    return {"ResultCode": 0, "ResultDesc": "ok"}
