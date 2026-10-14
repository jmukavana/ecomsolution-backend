from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth.csrf import CsrfMiddleware
from app.config import settings
from app.routers import (
    admin_catalog,
    admin_notifications,
    admin_orders,
    admin_uploads,
    auth,
    cart,
    catalog,
    checkout,
    health,
    me,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

    app.add_middleware(CsrfMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-CSRF-Token"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(catalog.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(cart.router, prefix="/api")
    app.include_router(checkout.router, prefix="/api")
    app.include_router(admin_catalog.router, prefix="/api")
    app.include_router(admin_notifications.router, prefix="/api")
    app.include_router(admin_orders.router, prefix="/api")
    app.include_router(admin_uploads.router, prefix="/api")

    # Serve uploaded images
    uploads_dir = Path(settings.STORAGE_LOCAL_DIR).resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
    return app


app = create_app()
