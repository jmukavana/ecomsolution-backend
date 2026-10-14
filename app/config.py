from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://ecom:ecom@127.0.0.1:5432/ecom"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://ecom:ecom@127.0.0.1:5432/ecom"

    # --- Sessions & CSRF ---
    SESSION_COOKIE_NAME: str = "sid"
    SESSION_TTL_DAYS: int = 14
    SESSION_SECRET: str = "change-me-please-32-bytes-minimum-secret"
    CSRF_COOKIE_NAME: str = "csrf"
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # --- Auth / OTP ---
    OTP_LENGTH: int = 6
    OTP_TTL_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RATE_LIMIT_PER_EMAIL_PER_MIN: int = 3
    OTP_RATE_LIMIT_PER_IP_PER_MIN: int = 10

    # --- Email ---
    EMAIL_BACKEND: Literal["console", "smtp"] = "console"
    MAIL_HOST: str = "zmail.emtechhouse.co.ke"
    MAIL_PORT: int = 465
    MAIL_USE_SSL: bool = True
    MAIL_USERNAME: str = "Banca-noreply@emtechhouse.co.ke"
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "Banca-noreply@emtechhouse.co.ke"
    MAIL_FROM_NAME: str = "Ecomsolution"

    # --- M-Pesa Daraja ---
    MPESA_ENV: Literal["sandbox", "production"] = "sandbox"
    MPESA_CONSUMER_KEY: str = ""
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = "174379"
    MPESA_PASSKEY: str = ""
    MPESA_CALLBACK_URL: str = ""

    # --- Storage ---
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_DIR: str = "./uploads"
    # S3 / R2 (only used when STORAGE_BACKEND=s3). For Cloudflare R2 set
    # S3_ENDPOINT_URL to https://<account>.r2.cloudflarestorage.com and
    # S3_REGION to "auto". S3_PUBLIC_BASE_URL is the public/CDN origin that
    # serves the bucket (e.g. https://cdn.example.co.ke).
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str | None = None
    S3_REGION: str = "auto"
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PUBLIC_BASE_URL: str = ""

    # --- Locale ---
    CURRENCY: str = "KES"
    DEFAULT_COUNTRY: str = "KE"

    APP_NAME: str = "Ecomsolution"
    DEBUG: bool = True

    # TEMPORARY admin guard until Phase 4 (real auth). Set to a long random string;
    # all /api/admin/* endpoints require this in X-Admin-Token until cookies+roles land.
    ADMIN_TOKEN: str = "dev-admin-token-change-me"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
