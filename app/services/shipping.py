"""Shipping cost calculation. Pluggable strategies, county-aware."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import ShippingZone

# Fallback when no shipping_zones row exists for the destination
DEFAULT_BASE_RATE = Decimal("400.00")
DEFAULT_PER_KG_RATE = Decimal("70.00")
DEFAULT_ETA_DAYS = 5

NAIROBI_BASE_RATE = Decimal("250.00")
NAIROBI_PER_KG_RATE = Decimal("50.00")
NAIROBI_ETA_DAYS = 2


@dataclass(slots=True)
class ShippingQuote:
    county: str
    cost: Decimal
    eta_days: int


async def quote_shipping(
    db: AsyncSession, *, county: str, total_weight_kg: Decimal
) -> ShippingQuote:
    """Look up the zone; fall back to defaults. Round to KSh whole shillings."""
    row = (
        await db.execute(select(ShippingZone).where(ShippingZone.county == county))
    ).scalar_one_or_none()

    if row is not None:
        base = row.base_rate
        per_kg = row.per_kg_rate
        eta = row.eta_days
    elif county == "Nairobi":
        base, per_kg, eta = NAIROBI_BASE_RATE, NAIROBI_PER_KG_RATE, NAIROBI_ETA_DAYS
    else:
        base, per_kg, eta = DEFAULT_BASE_RATE, DEFAULT_PER_KG_RATE, DEFAULT_ETA_DAYS

    cost = base + per_kg * max(total_weight_kg, Decimal("0"))
    return ShippingQuote(county=county, cost=cost.quantize(Decimal("1")), eta_days=eta)
