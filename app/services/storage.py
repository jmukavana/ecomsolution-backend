"""Pluggable file storage. Local-only for now; swap to S3 / R2 by
implementing FileStorage and switching the factory below.
"""

from __future__ import annotations

import io
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from app.config import settings

MAX_IMAGE_PIXELS = 1200  # longest edge after resize
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
EXT_FOR_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class FileStorage(Protocol):
    async def put_image(
        self, *, data: bytes, content_type: str, prefix: str = "products"
    ) -> str:
        """Persist an uploaded image; return a public URL (or relative path)."""
        ...


def _thumb(raw: bytes, content_type: str) -> tuple[bytes, str]:
    """Decode + downsize to MAX_IMAGE_PIXELS on longest edge. Returns
    (encoded_bytes, ext_to_save_as). Preserves original format where sensible.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except UnidentifiedImageError as e:
        raise ValueError("not a recognised image") from e

    img.thumbnail((MAX_IMAGE_PIXELS, MAX_IMAGE_PIXELS), Image.Resampling.LANCZOS)

    save_fmt = "JPEG" if content_type == "image/jpeg" else (
        "PNG" if content_type == "image/png" else
        "WEBP" if content_type == "image/webp" else "JPEG"
    )
    buf = io.BytesIO()
    save_kwargs = {"quality": 85, "optimize": True} if save_fmt == "JPEG" else {}
    if save_fmt == "JPEG" and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format=save_fmt, **save_kwargs)
    return buf.getvalue(), EXT_FOR_TYPE.get(content_type, "jpg")


class LocalFileStorage:
    """Writes under STORAGE_LOCAL_DIR; URLs served via FastAPI StaticFiles mount."""

    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    async def put_image(
        self, *, data: bytes, content_type: str, prefix: str = "products"
    ) -> str:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"unsupported content type: {content_type}")
        encoded, ext = _thumb(data, content_type)

        today = datetime.now(timezone.utc).strftime("%Y/%m")
        folder = self.base / prefix / today
        folder.mkdir(parents=True, exist_ok=True)

        name = f"{secrets.token_urlsafe(12)}.{ext}"
        path = folder / name
        path.write_bytes(encoded)

        # Relative URL — FastAPI mounts STORAGE_LOCAL_DIR at /uploads
        return f"/uploads/{prefix}/{today}/{name}"


def get_storage() -> FileStorage:
    return LocalFileStorage(settings.STORAGE_LOCAL_DIR)
