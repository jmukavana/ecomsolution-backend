"""Shared pytest fixtures: isolated test database + fresh schema per session."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

# Point the test DB at a dedicated database before app modules read settings
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://ecom:ecom@127.0.0.1:5432/ecom_test"
)
os.environ.setdefault("EMAIL_BACKEND", "console")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

# Import these AFTER env vars are set so settings see the test DB
from app.db import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
import app.models  # noqa: F401, E402  — register all models with Base.metadata


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema():
    """One-shot, synchronous schema reset before any test runs."""
    import asyncio as _asyncio

    async def _go():
        eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    _asyncio.run(_go())


@pytest_asyncio.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    """Fresh engine per test — NullPool means no cross-test connection bleed."""
    eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _truncate(engine: AsyncEngine) -> AsyncIterator[None]:
    """Clear DB rows between tests to keep them independent."""
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_engine() -> AsyncIterator[None]:
    """Dispose the app's global engine after each test.

    Endpoints that schedule background work (e.g. notification dispatch) use the
    module-level engine in `app.db`, not the per-test NullPool engine. Each test
    runs on its own event loop, so a connection pooled on one test's loop would
    blow up if reused by the next. Disposing clears that pool between tests.
    """
    yield
    from app.db import engine as app_engine

    await app_engine.dispose()


@pytest_asyncio.fixture()
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture()
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """An AsyncClient that talks to the FastAPI app in-process, with the test DB."""
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
