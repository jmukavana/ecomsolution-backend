from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.catalog import Category, Product
from app.schemas.catalog import (
    CategoryNode,
    ProductDetail,
    ProductListResponse,
    ProductSummary,
)
from app.services.catalog import (
    build_category_tree,
    get_attribute_set_for_category,
    get_descendant_category_ids,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/categories", response_model=list[CategoryNode])
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await build_category_tree(db)


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None, description="category slug"),
    brand: str | None = None,
    q: str | None = Query(None, description="search query (name/description/brand)"),
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    featured: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
) -> dict[str, Any]:
    stmt = select(Product).where(Product.is_active.is_(True))

    # Order: when there's a search query, rank by FTS relevance; otherwise
    # featured-first / newest-first.
    use_fts = bool(q and q.strip())
    if use_fts:
        ts_query = func.websearch_to_tsquery("english", q)
        ts_vector = literal_column("search_vector")
        rank = func.ts_rank(ts_vector, ts_query).label("rank")
        stmt = stmt.add_columns(rank).where(ts_vector.op("@@")(ts_query))
        stmt = stmt.order_by(text("rank DESC"), Product.id.desc())
    else:
        stmt = stmt.order_by(Product.is_featured.desc(), Product.id.desc())

    cat_id: int | None = None
    if category:
        cat_id = (
            await db.execute(select(Category.id).where(Category.slug == category))
        ).scalar_one_or_none()
        if cat_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "category not found")
        descendants = await get_descendant_category_ids(db, cat_id)
        stmt = stmt.where(Product.category_id.in_(descendants))

    if brand:
        stmt = stmt.where(Product.brand == brand)

    if featured is not None:
        stmt = stmt.where(Product.is_featured.is_(featured))

    if min_price is not None:
        stmt = stmt.where(Product.base_price_kes >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.base_price_kes <= max_price)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    if use_fts:
        items = [row[0] for row in (await db.execute(stmt)).all()]
    else:
        items = (await db.execute(stmt)).scalars().all()

    # Brand list for client-side filter chips (based on the un-filtered-by-brand result is harder;
    # for now return brands present in the current page result + popular brands overall)
    brands_stmt = (
        select(Product.brand)
        .where(Product.is_active.is_(True), Product.brand.is_not(None))
        .group_by(Product.brand)
        .order_by(func.count().desc())
        .limit(20)
    )
    brands = [b for (b,) in (await db.execute(brands_stmt)).all()]

    # Filterable attributes for the selected category (if any)
    filterable: list[dict[str, Any]] = []
    if cat_id is not None:
        attr_set = await get_attribute_set_for_category(db, cat_id)
        if attr_set is not None:
            filterable = [
                {
                    "key": d.key,
                    "label": d.label,
                    "data_type": d.data_type.value,
                    "unit": d.unit,
                    "options": d.options or [],
                }
                for d in attr_set.attributes
                if d.is_filterable
            ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "filters": {"brands": brands, "attributes": filterable},
    }


@router.get("/products/{slug}", response_model=ProductDetail)
async def get_product(slug: str, db: AsyncSession = Depends(get_db)) -> Product:
    stmt = (
        select(Product)
        .where(Product.slug == slug, Product.is_active.is_(True))
        .options(selectinload(Product.variants))
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")
    return product


@router.get("/categories/{slug}", response_model=CategoryNode)
async def get_category(slug: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    cat = (
        await db.execute(select(Category).where(Category.slug == slug))
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "category not found")

    children_stmt = (
        select(Category)
        .where(Category.parent_id == cat.id)
        .order_by(Category.position, Category.id)
    )
    children = (await db.execute(children_stmt)).scalars().all()

    return {
        "id": cat.id,
        "slug": cat.slug,
        "name": cat.name,
        "parent_id": cat.parent_id,
        "position": cat.position,
        "image": cat.image,
        "attribute_set_id": cat.attribute_set_id,
        "children": [
            {
                "id": c.id,
                "slug": c.slug,
                "name": c.name,
                "parent_id": c.parent_id,
                "position": c.position,
                "image": c.image,
                "attribute_set_id": c.attribute_set_id,
                "children": [],
            }
            for c in children
        ],
    }

