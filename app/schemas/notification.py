from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.notification import NotificationChannel, NotificationStatus


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    type: str
    channel: NotificationChannel
    title: str | None
    body: str
    payload: dict[str, Any]
    status: NotificationStatus
    attempts: int
    last_error: str | None
    scheduled_for: datetime | None
    sent_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class NotificationTestRequest(BaseModel):
    key: str = Field(min_length=1)
    to_email: EmailStr | None = None
    payload: dict[str, Any] = {}


class NotificationTestResponse(BaseModel):
    enqueued: int
    dispatched: int
    rows: list[NotificationOut]
