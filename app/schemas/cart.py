from typing import Any

from pydantic import BaseModel, Field


class AddItemIn(BaseModel):
    variant_id: int = Field(gt=0)
    qty: int = Field(gt=0, le=100)


class UpdateItemIn(BaseModel):
    qty: int = Field(ge=0, le=100)


class CartItemOut(BaseModel):
    id: int
    variant_id: int
    sku: str
    qty: int
    unit_price: str
    line_total: str
    stock: int
    product: dict[str, Any]
    options: dict[str, Any]


class CartOut(BaseModel):
    id: int
    items: list[CartItemOut]
    subtotal: str
    total_weight_kg: str
    item_count: int
