"""Schemas for customer self-service: profile, saved addresses, in-app notifications."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)


class AddressIn(BaseModel):
    county: str = Field(min_length=1, max_length=64)
    town: str = Field(min_length=1, max_length=128)
    street: str | None = Field(default=None, max_length=255)
    landmark: str | None = Field(default=None, max_length=255)
    phone: str = Field(min_length=7, max_length=20)
    is_default: bool = False


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    county: str
    town: str
    street: str | None
    landmark: str | None
    phone: str
    is_default: bool


class MyNotificationOut(BaseModel):
    """In-app notification as the owning customer sees it."""

    id: int
    type: str
    title: str | None
    body: str
    payload: dict[str, Any]
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread: int
