from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import require_admin
from app.models.catalog import Product, ProductVariant
from app.models.order import (
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.models.user import User
from app.notifications import dispatch_pending, enqueue
from app.schemas.admin import (
    DashboardStats,
    LowStockRow,
    OrderListResponse,
    OrderRow,
    StatusTransitionIn,
)
from app.schemas.order import OrderOut

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

LOW_STOCK_THRESHOLD = 5

# ---------- Orders ----------

@router.get("/orders", response_model=OrderListResponse)
async def list_orders(
    db: AsyncSession = Depends(get_db),
    status_filter: OrderStatus | None = Query(None, alias="status"),
    payment_method: PaymentMethod | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict:
    stmt = select(Order).order_by(Order.id.desc())
    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)
    if payment_method is not None:
        stmt = stmt.where(Order.payment_method == payment_method)

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)) -> Order:
    order = await db.get(
        Order, order_id,
        options=[selectinload(Order.items), selectinload(Order.payments)],
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    return order


# Allowed transitions — declared explicitly so admins can't skip stages by accident.
_ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED, OrderStatus.PAID},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}

_NOTIFICATION_KEY = {
    OrderStatus.PAID: "order.paid",
    OrderStatus.SHIPPED: "order.shipped",
    OrderStatus.DELIVERED: "order.delivered",
}


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
async def transition_order_status(
    order_id: int,
    payload: StatusTransitionIn,
    background: BackgroundTasks,
    admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> Order:
    order = await db.get(
        Order, order_id,
        options=[selectinload(Order.items), selectinload(Order.payments)],
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")

    target = OrderStatus(payload.status)
    allowed = _ALLOWED.get(order.status, set())
    if target not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cannot transition from {order.status.value} to {target.value}",
        )

    # Special handling: marking PAID manually (e.g. COD received) keeps payment row in sync.
    if target == OrderStatus.PAID:
        last_pay = order.payments[-1] if order.payments else None
        if last_pay is not None and last_pay.status != PaymentStatus.SUCCESS:
            last_pay.status = PaymentStatus.SUCCESS
            last_pay.completed_at = datetime.now(timezone.utc)

    # CANCELLED before SHIPPED → restock
    if target == OrderStatus.CANCELLED and order.status in (
        OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.PROCESSING
    ):
        for item in order.items:
            if item.variant_id is None:
                continue
            v = await db.get(ProductVariant, item.variant_id)
            if v is not None:
                v.stock += item.qty

    order.status = target

    # Fire notification if mapped
    key = _NOTIFICATION_KEY.get(target)
    if key:
        payload_data: dict = {"order_id": order.id, "total": str(order.total)}
        if target == OrderStatus.SHIPPED:
            if payload.courier:
                payload_data["courier"] = payload.courier
            if payload.tracking:
                payload_data["tracking"] = payload.tracking
        await enqueue(
            db,
            key=key,
            payload=payload_data,
            user_id=order.user_id,
            to_email=order.customer_email,
        )

    await db.commit()
    background.add_task(dispatch_pending, limit=5)
    _ = admin  # acknowledge admin (audit log noted as Phase 7 task)
    return order


# ---------- Dashboard stats ----------

@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    orders_today = (await db.execute(
        select(func.count()).where(Order.created_at >= start_of_day)
    )).scalar_one()

    orders_pending = (await db.execute(
        select(func.count()).where(Order.status == OrderStatus.PENDING)
    )).scalar_one()

    orders_paid_unshipped = (await db.execute(
        select(func.count()).where(
            Order.status.in_((OrderStatus.PAID, OrderStatus.PROCESSING))
        )
    )).scalar_one()

    # Revenue: sum of `total` for orders in delivered/paid/shipped this month
    revenue = (await db.execute(
        select(func.coalesce(func.sum(Order.total), 0))
        .where(
            Order.created_at >= start_of_month,
            Order.status.in_((OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED)),
        )
    )).scalar_one()

    # Orders by status (last 30 days)
    thirty_ago = now - timedelta(days=30)
    rows = (await db.execute(
        select(Order.status, func.count())
        .where(Order.created_at >= thirty_ago)
        .group_by(Order.status)
    )).all()
    by_status = {s.value if hasattr(s, "value") else str(s): c for s, c in rows}
    # Ensure every status appears
    for s in OrderStatus:
        by_status.setdefault(s.value, 0)

    low = (await db.execute(
        select(ProductVariant, Product)
        .join(Product, ProductVariant.product_id == Product.id)
        .where(ProductVariant.stock <= LOW_STOCK_THRESHOLD, Product.is_active.is_(True))
        .order_by(ProductVariant.stock.asc())
        .limit(10)
    )).all()
    low_stock = [
        LowStockRow(
            variant_id=v.id,
            sku=v.sku,
            product_id=p.id,
            product_slug=p.slug,
            product_name=p.name,
            stock=v.stock,
        )
        for v, p in low
    ]

    payments_failed_recent = (await db.execute(
        select(func.count())
        .where(
            Payment.status == PaymentStatus.FAILED,
            Payment.created_at >= now - timedelta(days=7),
        )
    )).scalar_one()

    return {
        "orders_today": orders_today,
        "orders_pending": orders_pending,
        "orders_paid_unshipped": orders_paid_unshipped,
        "revenue_this_month": str(Decimal(revenue or 0).quantize(Decimal("0.01"))),
        "orders_by_status": by_status,
        "low_stock": low_stock,
        "payments_failed_recent": payments_failed_recent,
    }


# unused-suppress
_ = OrderRow
