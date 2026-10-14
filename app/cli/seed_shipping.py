"""Seed shipping zones for KE counties with realistic defaults.

Run:
    uv run python -m app.cli.seed_shipping
"""

import asyncio
from decimal import Decimal

from sqlalchemy import delete

from app.constants.counties import KENYAN_COUNTIES
from app.db import SessionLocal
from app.models.order import ShippingZone

# Three tiers: Nairobi metro, major regional cities, upcountry.
URBAN = {"Nairobi", "Kiambu", "Machakos", "Kajiado"}
REGIONAL = {"Mombasa", "Kisumu", "Nakuru", "Uasin Gishu", "Nyeri", "Eldoret", "Meru", "Kakamega"}


async def seed() -> None:
    async with SessionLocal() as db:
        await db.execute(delete(ShippingZone))
        for county in KENYAN_COUNTIES:
            if county in URBAN:
                base, per_kg, eta = Decimal("250"), Decimal("50"), 2
            elif county in REGIONAL:
                base, per_kg, eta = Decimal("400"), Decimal("70"), 3
            else:
                base, per_kg, eta = Decimal("550"), Decimal("90"), 5
            db.add(
                ShippingZone(
                    county=county, base_rate=base, per_kg_rate=per_kg, eta_days=eta
                )
            )
        await db.commit()
        print(f"Seeded shipping zones for {len(KENYAN_COUNTIES)} counties.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
