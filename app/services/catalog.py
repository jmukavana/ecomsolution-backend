from collections import defaultdict
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import (
    AttributeDataType,
    AttributeDefinition,
    AttributeSet,
    Category,
)


async def build_category_tree(db: AsyncSession) -> list[dict[str, Any]]:
    """Return categories as a nested tree ordered by position."""
    result = await db.execute(select(Category).order_by(Category.position, Category.id))
    rows = result.scalars().all()

    by_parent: dict[int | None, list[Category]] = defaultdict(list)
    for row in rows:
        by_parent[row.parent_id].append(row)

    def to_node(c: Category) -> dict[str, Any]:
        return {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "parent_id": c.parent_id,
            "position": c.position,
            "image": c.image,
            "attribute_set_id": c.attribute_set_id,
            "children": [to_node(child) for child in by_parent.get(c.id, [])],
        }

    return [to_node(c) for c in by_parent.get(None, [])]


async def get_descendant_category_ids(db: AsyncSession, root_id: int) -> list[int]:
    """Return the root id plus all its descendants (BFS through `parent_id`)."""
    result_ids: list[int] = [root_id]
    frontier: list[int] = [root_id]
    while frontier:
        rows = await db.execute(select(Category.id).where(Category.parent_id.in_(frontier)))
        next_ids = [r[0] for r in rows.all()]
        if not next_ids:
            break
        result_ids.extend(next_ids)
        frontier = next_ids
    return result_ids


async def get_attribute_set_for_category(
    db: AsyncSession, category_id: int | None
) -> AttributeSet | None:
    """Walk up the category tree to find an inherited attribute set."""
    if category_id is None:
        return None
    current_id: int | None = category_id
    visited: set[int] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        cat = await db.get(
            Category, current_id, options=[selectinload(Category.attribute_set).selectinload(AttributeSet.attributes)]
        )
        if cat is None:
            return None
        if cat.attribute_set_id is not None:
            return cat.attribute_set
        current_id = cat.parent_id
    return None


def _coerce(value: Any, data_type: AttributeDataType) -> Any:
    """Validate + coerce a single value against a definition's data_type."""
    if data_type == AttributeDataType.TEXT:
        if not isinstance(value, str):
            raise ValueError("expected string")
        return value
    if data_type == AttributeDataType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected number")
        return value
    if data_type == AttributeDataType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError("expected boolean")
        return value
    if data_type == AttributeDataType.ENUM:
        if not isinstance(value, str):
            raise ValueError("expected string for enum")
        return value
    if data_type == AttributeDataType.DATE:
        if isinstance(value, str):
            date.fromisoformat(value)
            return value
        raise ValueError("expected ISO date string")
    raise ValueError(f"unsupported data type: {data_type}")


def validate_attributes(
    attrs: dict[str, Any], definitions: list[AttributeDefinition]
) -> dict[str, Any]:
    """Validate a product's attributes against an attribute set's definitions.

    - Required attributes must be present.
    - Each provided attribute must match its declared data type.
    - Enum values must be in `options`.
    - Unknown keys are dropped (not allowed) — raises 422 instead, so admins notice typos.
    """
    by_key = {d.key: d for d in definitions}
    cleaned: dict[str, Any] = {}
    errors: list[str] = []

    for d in definitions:
        if d.is_required and d.key not in attrs:
            errors.append(f"missing required attribute: '{d.key}'")

    for key, raw in attrs.items():
        definition = by_key.get(key)
        if definition is None:
            errors.append(f"unknown attribute: '{key}'")
            continue
        try:
            value = _coerce(raw, definition.data_type)
        except ValueError as e:
            errors.append(f"'{key}': {e}")
            continue
        if definition.data_type == AttributeDataType.ENUM:
            opts = definition.options or []
            if value not in opts:
                errors.append(f"'{key}' must be one of {opts}")
                continue
        cleaned[key] = value

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"attribute_errors": errors},
        )
    return cleaned
