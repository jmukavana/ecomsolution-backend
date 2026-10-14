from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.catalog import AttributeDataType


# ---------- Attribute definitions ----------

class AttributeDefinitionIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    data_type: AttributeDataType
    unit: str | None = None
    options: list[str] | None = None
    is_required: bool = False
    is_filterable: bool = False
    position: int = 0


class AttributeDefinitionOut(AttributeDefinitionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Attribute sets ----------

class AttributeSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    attributes: list[AttributeDefinitionIn] = []


class AttributeSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    attributes: list[AttributeDefinitionOut] = []


# ---------- Categories ----------

class CategoryIn(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    position: int = 0
    image: str | None = None
    attribute_set_id: int | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    parent_id: int | None
    position: int
    image: str | None
    attribute_set_id: int | None


class CategoryNode(CategoryOut):
    children: list["CategoryNode"] = []


# ---------- Variants ----------

class ProductVariantIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    option_values: dict[str, Any] = {}
    price_kes: Decimal
    stock: int = 0
    weight_kg: Decimal | None = None
    image_url: str | None = None


class ProductVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    option_values: dict[str, Any]
    price_kes: Decimal
    stock: int
    weight_kg: Decimal | None
    image_url: str | None


# ---------- Products ----------

class ProductImage(BaseModel):
    url: str
    alt: str | None = None
    position: int = 0


class ProductIn(BaseModel):
    slug: str = Field(min_length=1, max_length=160)
    sku: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    brand: str | None = None
    category_id: int | None = None
    base_price_kes: Decimal | None = None
    is_active: bool = True
    is_featured: bool = False
    images: list[ProductImage] = []
    attributes: dict[str, Any] = {}
    weight_kg: Decimal | None = None
    variants: list[ProductVariantIn] = []


class ProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    brand: str | None
    category_id: int | None
    base_price_kes: Decimal | None
    is_active: bool
    is_featured: bool
    images: list[ProductImage]


class ProductDetail(ProductSummary):
    description: str | None
    attributes: dict[str, Any]
    weight_kg: Decimal | None
    variants: list[ProductVariantOut]


class ProductListResponse(BaseModel):
    items: list[ProductSummary]
    total: int
    page: int
    page_size: int
    filters: dict[str, Any]
