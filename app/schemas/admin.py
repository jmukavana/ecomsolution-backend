from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus, PaymentMethod, PaymentStatus
from app.schemas.order import Money


class OrderRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: OrderStatus
    payment_method: PaymentMethod
    total: Money
    customer_email: str
    customer_name: str | None
    created_at: datetime


class OrderListResponse(BaseModel):
    items: list[OrderRow]
    total: int
    page: int
    page_size: int


class StatusTransitionIn(BaseModel):
    status: Literal["processing", "shipped", "delivered", "cancelled", "paid"]
    courier: str | None = None
    tracking: str | None = None


class LowStockRow(BaseModel):
    variant_id: int
    sku: str
    product_id: int
    product_slug: str
    product_name: str
    stock: int


class DashboardStats(BaseModel):
    orders_today: int
    orders_pending: int
    orders_paid_unshipped: int
    revenue_this_month: Money
    orders_by_status: dict[str, int]
    low_stock: list[LowStockRow]
    payments_failed_recent: int


class AdminProductRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    brand: str | None
    is_active: bool
    is_featured: bool
    base_price_kes: Money | None
    category_id: int | None


class AdminProductPatch(BaseModel):
    name: str | None = None
    brand: str | None = None
    base_price_kes: float | None = None
    is_active: bool | None = None
    is_featured: bool | None = None
    description: str | None = None
