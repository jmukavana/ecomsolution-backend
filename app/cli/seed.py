"""Seed two product types to prove the catalog is generic.

Run:
    uv run python -m app.cli.seed
"""

import asyncio
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models.catalog import (
    AttributeDataType,
    AttributeDefinition,
    AttributeSet,
    Category,
    Product,
    ProductVariant,
)


async def seed() -> None:
    async with SessionLocal() as db:
        # Wipe in dependency order (variants → products → categories → defs → sets)
        await db.execute(delete(ProductVariant))
        await db.execute(delete(Product))
        await db.execute(delete(Category))
        await db.execute(delete(AttributeDefinition))
        await db.execute(delete(AttributeSet))
        await db.commit()

        # === Attribute sets ===
        electronics_set = AttributeSet(name="Electronics")
        electronics_set.attributes = [
            AttributeDefinition(
                key="warranty_months", label="Warranty (months)",
                data_type=AttributeDataType.NUMBER, unit="months",
                is_required=True, is_filterable=True, position=0,
            ),
            AttributeDefinition(
                key="condition", label="Condition",
                data_type=AttributeDataType.ENUM, options=["new", "refurbished"],
                is_required=True, is_filterable=True, position=1,
            ),
            AttributeDefinition(
                key="screen_size_in", label="Screen size",
                data_type=AttributeDataType.NUMBER, unit="in",
                is_filterable=True, position=2,
            ),
            AttributeDefinition(
                key="features", label="Notes",
                data_type=AttributeDataType.TEXT, position=3,
            ),
        ]

        clothing_set = AttributeSet(name="Clothing")
        clothing_set.attributes = [
            AttributeDefinition(
                key="material", label="Material",
                data_type=AttributeDataType.ENUM,
                options=["cotton", "polyester", "wool", "linen", "blend"],
                is_required=True, is_filterable=True, position=0,
            ),
            AttributeDefinition(
                key="care", label="Care",
                data_type=AttributeDataType.TEXT, position=1,
            ),
            AttributeDefinition(
                key="unisex", label="Unisex",
                data_type=AttributeDataType.BOOLEAN, is_filterable=True, position=2,
            ),
        ]

        db.add_all([electronics_set, clothing_set])
        await db.flush()

        # === Categories ===
        electronics = Category(
            slug="electronics", name="Electronics", position=0,
            attribute_set_id=electronics_set.id,
        )
        clothing = Category(
            slug="clothing", name="Clothing", position=1,
            attribute_set_id=clothing_set.id,
        )
        db.add_all([electronics, clothing])
        await db.flush()

        laptops = Category(
            slug="laptops", name="Laptops", parent_id=electronics.id, position=0,
        )
        phones = Category(
            slug="phones", name="Phones", parent_id=electronics.id, position=1,
        )
        tshirts = Category(
            slug="t-shirts", name="T-Shirts", parent_id=clothing.id, position=0,
        )
        db.add_all([laptops, phones, tshirts])
        await db.flush()

        # === Products ===
        products = [
            Product(
                slug="hp-pavilion-15",
                sku="HP-PAV-15",
                name="HP Pavilion 15",
                description="15.6\" laptop, Intel Core i5, 8GB RAM, 512GB SSD.",
                brand="HP",
                category_id=laptops.id,
                base_price_kes=Decimal("78000.00"),
                is_active=True,
                is_featured=True,
                images=[{"url": "/img/hp-pavilion.jpg", "alt": "HP Pavilion", "position": 0}],
                attributes={
                    "warranty_months": 12,
                    "condition": "new",
                    "screen_size_in": 15.6,
                    "features": "Backlit keyboard, fingerprint reader",
                },
                weight_kg=Decimal("1.75"),
                variants=[
                    ProductVariant(
                        sku="HP-PAV-15-8GB-512",
                        option_values={"ram": "8GB", "storage": "512GB"},
                        price_kes=Decimal("78000.00"), stock=12, weight_kg=Decimal("1.75"),
                    ),
                    ProductVariant(
                        sku="HP-PAV-15-16GB-1TB",
                        option_values={"ram": "16GB", "storage": "1TB"},
                        price_kes=Decimal("96500.00"), stock=5, weight_kg=Decimal("1.78"),
                    ),
                ],
            ),
            Product(
                slug="samsung-galaxy-a55",
                sku="SAM-A55",
                name="Samsung Galaxy A55",
                description="6.6\" AMOLED display, 50MP triple camera.",
                brand="Samsung",
                category_id=phones.id,
                base_price_kes=Decimal("45500.00"),
                is_active=True,
                is_featured=True,
                images=[{"url": "/img/galaxy-a55.jpg", "alt": "Galaxy A55", "position": 0}],
                attributes={
                    "warranty_months": 24,
                    "condition": "new",
                    "screen_size_in": 6.6,
                    "features": "5G, IP67 water resistance",
                },
                weight_kg=Decimal("0.213"),
                variants=[
                    ProductVariant(
                        sku="SAM-A55-128-BLACK",
                        option_values={"storage": "128GB", "color": "awesome navy"},
                        price_kes=Decimal("45500.00"), stock=20,
                    ),
                    ProductVariant(
                        sku="SAM-A55-256-BLACK",
                        option_values={"storage": "256GB", "color": "awesome navy"},
                        price_kes=Decimal("52000.00"), stock=8,
                    ),
                    ProductVariant(
                        sku="SAM-A55-256-ICE",
                        option_values={"storage": "256GB", "color": "awesome iceblue"},
                        price_kes=Decimal("52000.00"), stock=11,
                    ),
                ],
            ),
            Product(
                slug="oraimo-freepods-3",
                sku="ORA-FP3",
                name="Oraimo FreePods 3",
                description="Wireless earbuds with active noise cancellation.",
                brand="Oraimo",
                category_id=phones.id,
                base_price_kes=Decimal("4500.00"),
                is_active=True,
                images=[{"url": "/img/freepods-3.jpg", "alt": "Oraimo FreePods 3", "position": 0}],
                attributes={
                    "warranty_months": 6,
                    "condition": "new",
                    "features": "Bluetooth 5.2, 30h playtime",
                },
                weight_kg=Decimal("0.046"),
                variants=[
                    ProductVariant(
                        sku="ORA-FP3-WHITE",
                        option_values={"color": "white"},
                        price_kes=Decimal("4500.00"), stock=40,
                    ),
                ],
            ),
            Product(
                slug="classic-cotton-tee",
                sku="TEE-CL",
                name="Classic Cotton Tee",
                description="Soft 180gsm cotton tee, regular fit.",
                brand="Jaml Threads",
                category_id=tshirts.id,
                base_price_kes=Decimal("1200.00"),
                is_active=True,
                is_featured=True,
                images=[{"url": "/img/tee-classic.jpg", "alt": "Classic Tee", "position": 0}],
                attributes={
                    "material": "cotton",
                    "care": "Machine wash cold; tumble dry low.",
                    "unisex": True,
                },
                weight_kg=Decimal("0.18"),
                variants=[
                    ProductVariant(
                        sku="TEE-CL-S-BLK", option_values={"size": "S", "color": "black"},
                        price_kes=Decimal("1200.00"), stock=15,
                    ),
                    ProductVariant(
                        sku="TEE-CL-M-BLK", option_values={"size": "M", "color": "black"},
                        price_kes=Decimal("1200.00"), stock=22,
                    ),
                    ProductVariant(
                        sku="TEE-CL-L-BLK", option_values={"size": "L", "color": "black"},
                        price_kes=Decimal("1200.00"), stock=18,
                    ),
                    ProductVariant(
                        sku="TEE-CL-M-WHT", option_values={"size": "M", "color": "white"},
                        price_kes=Decimal("1200.00"), stock=20,
                    ),
                    ProductVariant(
                        sku="TEE-CL-L-WHT", option_values={"size": "L", "color": "white"},
                        price_kes=Decimal("1200.00"), stock=12,
                    ),
                ],
            ),
            Product(
                slug="merino-crewneck",
                sku="MER-CR",
                name="Merino Crewneck Sweater",
                description="Lightweight merino wool, perfect for highland evenings.",
                brand="Jaml Threads",
                category_id=tshirts.id,
                base_price_kes=Decimal("3800.00"),
                is_active=True,
                images=[{"url": "/img/merino.jpg", "alt": "Merino Crewneck", "position": 0}],
                attributes={
                    "material": "wool",
                    "care": "Hand wash cold; dry flat.",
                    "unisex": False,
                },
                weight_kg=Decimal("0.42"),
                variants=[
                    ProductVariant(
                        sku="MER-CR-S-NAV", option_values={"size": "S", "color": "navy"},
                        price_kes=Decimal("3800.00"), stock=6,
                    ),
                    ProductVariant(
                        sku="MER-CR-M-NAV", option_values={"size": "M", "color": "navy"},
                        price_kes=Decimal("3800.00"), stock=9,
                    ),
                ],
            ),
        ]

        db.add_all(products)
        await db.commit()

        # Report
        q = await db.execute(
            select(Product).options(selectinload(Product.variants)).order_by(Product.id)
        )
        rows = q.scalars().all()
        print(f"Seeded {len(rows)} products:")
        for p in rows:
            print(
                f"  - {p.slug:<24} {p.brand or '':<14} "
                f"variants={len(p.variants):<2} attrs={list(p.attributes.keys())}"
            )


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
