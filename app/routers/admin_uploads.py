from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.deps import require_admin_or_bootstrap_token
from app.services.storage import ALLOWED_CONTENT_TYPES, get_storage

router = APIRouter(
    prefix="/admin/uploads",
    tags=["admin-uploads"],
    dependencies=[Depends(require_admin_or_bootstrap_token)],
)

MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_image(file: UploadFile = File(...)) -> dict:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"content type {file.content_type} not allowed",
        )
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "image too large")

    storage = get_storage()
    try:
        url = await storage.put_image(data=data, content_type=file.content_type)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"url": url, "size_bytes": len(data)}
