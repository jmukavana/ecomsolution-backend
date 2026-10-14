"""Admin catalog editors: attribute-set + category create/update/delete.

Uses the bootstrap ADMIN_TOKEN header (require_admin_or_bootstrap_token) so we
don't need a full admin MFA session just to exercise CRUD wiring.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings

AUTH = {"X-Admin-Token": settings.ADMIN_TOKEN}


@pytest.mark.asyncio
async def test_admin_routes_require_auth(client: AsyncClient):
    res = await client.get("/api/admin/catalog/categories")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_attribute_set_create_update_delete(client: AsyncClient):
    # Create with two definitions.
    res = await client.post(
        "/api/admin/catalog/attribute-sets",
        headers=AUTH,
        json={
            "name": "Electronics",
            "attributes": [
                {"key": "warranty_months", "label": "Warranty", "data_type": "number", "is_required": True},
                {"key": "condition", "label": "Condition", "data_type": "enum", "options": ["new", "used"]},
            ],
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()
    set_id = created["id"]
    assert len(created["attributes"]) == 2

    # Update: rename + replace definitions with a single one.
    res = await client.put(
        f"/api/admin/catalog/attribute-sets/{set_id}",
        headers=AUTH,
        json={
            "name": "Electronics & Gadgets",
            "attributes": [
                {"key": "screen_size_in", "label": "Screen size", "data_type": "number", "unit": "in", "is_filterable": True},
            ],
        },
    )
    assert res.status_code == 200, res.text
    updated = res.json()
    assert updated["name"] == "Electronics & Gadgets"
    assert [a["key"] for a in updated["attributes"]] == ["screen_size_in"]

    # Delete.
    res = await client.delete(f"/api/admin/catalog/attribute-sets/{set_id}", headers=AUTH)
    assert res.status_code == 204
    res = await client.get("/api/admin/catalog/attribute-sets", headers=AUTH)
    assert all(s["id"] != set_id for s in res.json())


@pytest.mark.asyncio
async def test_category_create_update_delete(client: AsyncClient):
    res = await client.post(
        "/api/admin/catalog/categories",
        headers=AUTH,
        json={"slug": "phones", "name": "Phones"},
    )
    assert res.status_code == 201, res.text
    cat_id = res.json()["id"]

    res = await client.put(
        f"/api/admin/catalog/categories/{cat_id}",
        headers=AUTH,
        json={"slug": "phones", "name": "Mobile Phones", "position": 2},
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Mobile Phones"
    assert res.json()["position"] == 2

    # A category can't be its own parent.
    res = await client.put(
        f"/api/admin/catalog/categories/{cat_id}",
        headers=AUTH,
        json={"slug": "phones", "name": "Mobile Phones", "parent_id": cat_id},
    )
    assert res.status_code == 400

    res = await client.delete(f"/api/admin/catalog/categories/{cat_id}", headers=AUTH)
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_category_slug_conflict(client: AsyncClient):
    for _ in range(1):
        res = await client.post(
            "/api/admin/catalog/categories",
            headers=AUTH,
            json={"slug": "dupe", "name": "First"},
        )
        assert res.status_code == 201, res.text
    res = await client.post(
        "/api/admin/catalog/categories",
        headers=AUTH,
        json={"slug": "dupe", "name": "Second"},
    )
    assert res.status_code == 409
