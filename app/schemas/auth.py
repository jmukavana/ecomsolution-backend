from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class RequestOtpIn(BaseModel):
    email: EmailStr


class RequestOtpOut(BaseModel):
    sent: bool = True
    ttl_minutes: int


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


class VerifyOtpOut(BaseModel):
    next: Literal["home", "mfa"]


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str | None
    phone: str | None
    role: UserRole
    mfa_required: bool
    mfa_passed: bool
    email_verified_at: datetime | None
    has_mfa_factor: bool


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    current: bool = False


class MfaStartOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class MfaVerifyOut(BaseModel):
    verified: bool = True
    recovery_codes: list[str] | None = None


class TotpStepUpIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)
