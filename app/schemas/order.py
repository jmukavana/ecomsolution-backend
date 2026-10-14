from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

from app.models.order import OrderStatus, PaymentMethod, PaymentStatus


def _decimal_to_str(v: Any) -> str:
    if isinstance(v, Decimal):
        return format(v.quantize(Decimal("0.01")), "f")
    return str(v) if v is not None else "0.00"


Money = Annotated[str, BeforeValidator(_decimal_to_str)]


class ShippingAddressIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    county: str
    town: str
    street: str | None = None
    landmark: str | None = None
    phone: str = Field(min_length=7, max_length=20)
    notes: str | None = None


class QuoteIn(BaseModel):
    county: str


class QuoteOut(BaseModel):
    subtotal: str
    shipping: str
    tax: str
    total: str
    eta_days: int
    county: str


class CheckoutIn(BaseModel):
    payment_method: Literal["mpesa", "cod"]
    shipping_address: ShippingAddressIn
    customer_email: EmailStr
    customer_phone: str = Field(min_length=7, max_length=20)
    customer_name: str | None = None


class CheckoutOut(BaseModel):
    order_id: int
    status: OrderStatus
    payment_method: PaymentMethod
    total: str
    next: str
    checkout_request_id: str | None
    customer_message: str | None


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    qty: int
    unit_price: Money
    product_name: str
    sku: str
    options: dict[str, Any]


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: PaymentMethod
    status: PaymentStatus
    amount: Money
    checkout_request_id: str | None
    mpesa_receipt: str | None
    completed_at: datetime | None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: OrderStatus
    payment_method: PaymentMethod
    subtotal: Money
    shipping: Money
    tax: Money
    total: Money
    shipping_address: dict[str, Any]
    customer_email: str
    customer_phone: str
    customer_name: str | None
    created_at: datetime
    items: list[OrderItemOut]
    payments: list[PaymentOut]


class OrderSummaryOut(BaseModel):
    """Compact order row for a customer's order-history list."""

    id: int
    status: OrderStatus
    payment_method: PaymentMethod
    total: Money
    item_count: int
    created_at: datetime
