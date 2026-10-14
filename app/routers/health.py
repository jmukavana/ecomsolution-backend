from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(text("SELECT 1"))
    db_ok = result.scalar() == 1
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME,
        "db": "ok" if db_ok else "down",
    }
