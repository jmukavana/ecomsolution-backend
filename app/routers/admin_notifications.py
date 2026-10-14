from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin_or_bootstrap_token
from app.models.notification import Notification, NotificationStatus
from app.notifications import dispatch_pending, enqueue
from app.schemas.notification import (
    NotificationOut,
    NotificationTestRequest,
    NotificationTestResponse,
)

router = APIRouter(
    prefix="/admin/notifications",
    tags=["admin-notifications"],
    dependencies=[Depends(require_admin_or_bootstrap_token)],
)


@router.post("/test", response_model=NotificationTestResponse)
async def send_test_notification(
    payload: NotificationTestRequest,
    background: BackgroundTasks,
    sync: bool = Query(False, description="If true, dispatch inline (don't background)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not payload.to_email and not payload.payload.get("email"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Provide to_email or payload.email",
        )
    rows = await enqueue(
        db,
        key=payload.key,
        payload=payload.payload,
        to_email=payload.to_email or payload.payload.get("email"),
    )
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No active templates for key '{payload.key}'",
        )
    await db.commit()

    dispatched = 0
    if sync:
        dispatched = await dispatch_pending(limit=len(rows))
    else:
        background.add_task(dispatch_pending, limit=len(rows))

    # Re-fetch row state after potential sync dispatch (dispatch ran in its own
    # session, so we must invalidate this session's identity-map cache first).
    if sync:
        ids = [r.id for r in rows]
        db.expire_all()
        stmt = select(Notification).where(Notification.id.in_(ids))
        rows = list((await db.execute(stmt)).scalars().all())

    return {"enqueued": len(rows), "dispatched": dispatched, "rows": rows}


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    status_filter: NotificationStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.id.desc()).limit(limit)
    if status_filter is not None:
        stmt = stmt.where(Notification.status == status_filter)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/dispatch", status_code=status.HTTP_200_OK)
async def dispatch_now(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Force a dispatch pass (useful in tests / cron-less local dev)."""
    n = await dispatch_pending(limit=limit)
    return {"dispatched": n}
