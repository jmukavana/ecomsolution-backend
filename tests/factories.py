"""Tiny object factories — built directly with SQLAlchemy models, no fancy lib."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import (
    AttributeDataType,
    AttributeDefinition,
    AttributeSet,
    Category,
    Product,
    ProductVariant,
)
from app.models.order import ShippingZone


async def make_attribute_set(db: AsyncSession, name: str = "Generic") -> AttributeSet:
    s = AttributeSet(name=name)
    s.attributes = [
        AttributeDefinition(
            key="warranty_months",
            label="Warranty",
            data_type=AttributeDataType.NUMBER,
            unit="months",
            is_required=True,
            position=0,
        ),
        AttributeDefinition(
            key="condition",
            label="Condition",
            data_type=AttributeDataType.ENUM,
            options=["new", "refurbished"],
            is_required=True,
            position=1,
        ),
    ]
    db.add(s)
    await db.flush()
    return s


async def make_product(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    price: str = "10000",
    stock: int = 10,
    category: Category | None = None,
) -> Product:
    p = Product(
        slug=slug,
        sku=slug.upper(),
        name=name,
        brand="Test",
        category_id=category.id if category else None,
        base_price_kes=Decimal(price),
        is_active=True,
        images=[],
        attributes={},
        weight_kg=Decimal("0.5"),
    )
    p.variants = [
        ProductVariant(
            sku=f"{slug.upper()}-DEFAULT",
            option_values={"variant": "default"},
            price_kes=Decimal(price),
            stock=stock,
        )
    ]
    db.add(p)
    await db.flush()
    return p


async def seed_shipping(db: AsyncSession) -> None:
    db.add(
        ShippingZone(
            county="Nairobi", base_rate=Decimal("250"),
            per_kg_rate=Decimal("50"), eta_days=2,
        )
    )
    await db.flush()
