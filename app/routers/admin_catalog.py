from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import require_admin_or_bootstrap_token
from app.models.catalog import (
    AttributeDefinition,
    AttributeSet,
    Category,
    Product,
    ProductVariant,
)
from app.schemas.catalog import (
    AttributeSetIn,
    AttributeSetOut,
    CategoryIn,
    CategoryOut,
    ProductDetail,
    ProductIn,
)
from app.services.catalog import (
    get_attribute_set_for_category,
    validate_attributes,
)

router = APIRouter(
    prefix="/admin/catalog",
    tags=["admin-catalog"],
    dependencies=[Depends(require_admin_or_bootstrap_token)],
)


# ---------- Attribute sets ----------

@router.post("/attribute-sets", response_model=AttributeSetOut, status_code=status.HTTP_201_CREATED)
async def create_attribute_set(
    payload: AttributeSetIn, db: AsyncSession = Depends(get_db)
) -> AttributeSet:
    attr_set = AttributeSet(name=payload.name)
    for d in payload.attributes:
        attr_set.attributes.append(AttributeDefinition(**d.model_dump()))
    db.add(attr_set)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "attribute set name conflict") from e
    await db.refresh(attr_set, ["attributes"])
    return attr_set


@router.get("/attribute-sets", response_model=list[AttributeSetOut])
async def list_attribute_sets(db: AsyncSession = Depends(get_db)) -> list[AttributeSet]:
    stmt = (
        select(AttributeSet)
        .options(selectinload(AttributeSet.attributes))
        .order_by(AttributeSet.id)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.put("/attribute-sets/{set_id}", response_model=AttributeSetOut)
async def update_attribute_set(
    set_id: int, payload: AttributeSetIn, db: AsyncSession = Depends(get_db)
) -> AttributeSet:
    attr_set = await db.get(
        AttributeSet, set_id, options=[selectinload(AttributeSet.attributes)]
    )
    if attr_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "attribute set not found")
    attr_set.name = payload.name
    # Replace the definitions wholesale (delete-orphan cascade drops the old ones).
    attr_set.attributes.clear()
    for d in payload.attributes:
        attr_set.attributes.append(AttributeDefinition(**d.model_dump()))
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "attribute set name conflict") from e
    await db.refresh(attr_set, ["attributes"])
    return attr_set


@router.delete("/attribute-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attribute_set(set_id: int, db: AsyncSession = Depends(get_db)) -> None:
    attr_set = await db.get(AttributeSet, set_id)
    if attr_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "attribute set not found")
    # Categories referencing this set have attribute_set_id set to NULL (FK rule).
    await db.delete(attr_set)
    await db.commit()


# ---------- Categories ----------

@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryIn, db: AsyncSession = Depends(get_db)
) -> Category:
    cat = Category(**payload.model_dump())
    db.add(cat)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug conflict") from e
    await db.refresh(cat)
    return cat


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories_admin(db: AsyncSession = Depends(get_db)) -> list[Category]:
    stmt = select(Category).order_by(Category.position, Category.id)
    return list((await db.execute(stmt)).scalars().all())


@router.put("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, payload: CategoryIn, db: AsyncSession = Depends(get_db)
) -> Category:
    cat = await db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "category not found")
    if payload.parent_id == category_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "category cannot be its own parent")
    for key, value in payload.model_dump().items():
        setattr(cat, key, value)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug conflict") from e
    await db.refresh(cat)
    return cat


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: int, db: AsyncSession = Depends(get_db)) -> None:
    cat = await db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "category not found")
    # Child categories and products have their FK set to NULL (see model rules).
    await db.delete(cat)
    await db.commit()


# ---------- Products ----------

async def _validate_product_attributes(
    db: AsyncSession, payload: ProductIn
) -> dict[str, Any]:
    if not payload.attributes:
        return {}
    attr_set = await get_attribute_set_for_category(db, payload.category_id)
    if attr_set is None:
        # If no attribute set is configured for this branch, accept attributes as-is.
        return dict(payload.attributes)
    return validate_attributes(payload.attributes, list(attr_set.attributes))


@router.post("/products", response_model=ProductDetail, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductIn, db: AsyncSession = Depends(get_db)
) -> Product:
    cleaned_attrs = await _validate_product_attributes(db, payload)

    product = Product(
        slug=payload.slug,
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        brand=payload.brand,
        category_id=payload.category_id,
        base_price_kes=payload.base_price_kes,
        is_active=payload.is_active,
        is_featured=payload.is_featured,
        images=[img.model_dump() for img in payload.images],
        attributes=cleaned_attrs,
        weight_kg=payload.weight_kg,
    )
    for v in payload.variants:
        product.variants.append(ProductVariant(**v.model_dump()))

    db.add(product)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug or sku conflict") from e
    await db.refresh(product, ["variants"])
    return product


@router.put("/products/{product_id}", response_model=ProductDetail)
async def update_product(
    product_id: int, payload: ProductIn, db: AsyncSession = Depends(get_db)
) -> Product:
    product = await db.get(Product, product_id, options=[selectinload(Product.variants)])
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")

    cleaned_attrs = await _validate_product_attributes(db, payload)
    product.slug = payload.slug
    product.sku = payload.sku
    product.name = payload.name
    product.description = payload.description
    product.brand = payload.brand
    product.category_id = payload.category_id
    product.base_price_kes = payload.base_price_kes
    product.is_active = payload.is_active
    product.is_featured = payload.is_featured
    product.images = [img.model_dump() for img in payload.images]
    product.attributes = cleaned_attrs
    product.weight_kg = payload.weight_kg

    # Replace variants entirely (simplest predictable semantics for v1)
    product.variants.clear()
    for v in payload.variants:
        product.variants.append(ProductVariant(**v.model_dump()))

    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "slug or sku conflict") from e
    await db.refresh(product, ["variants"])
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)) -> None:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")
    await db.delete(product)
    await db.commit()


# ---------- Admin-only product list (includes inactive) ----------

from app.schemas.admin import AdminProductPatch, AdminProductRow  # noqa: E402


@router.get("/products", response_model=list[AdminProductRow])
async def list_products_admin(
    db: AsyncSession = Depends(get_db),
    q: str | None = None,
    include_inactive: bool = True,
) -> list[Product]:
    stmt = select(Product).order_by(Product.id.desc()).limit(200)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func as _f
        stmt = stmt.where(
            _f.lower(Product.name).like(like) | _f.lower(_f.coalesce(Product.brand, "")).like(like)
        )
    return list((await db.execute(stmt)).scalars().all())


@router.patch("/products/{product_id}/basics", response_model=AdminProductRow)
async def patch_product_basics(
    product_id: int,
    payload: AdminProductPatch,
    db: AsyncSession = Depends(get_db),
) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return product
