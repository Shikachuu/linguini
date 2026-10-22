"""FastAPI application factory and lifespan."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from linguini.auth.oidc import JwksCache
from linguini.auth.router import router as auth_router
from linguini.auth.sessions import CsrfMiddleware
from linguini.config import Settings, get_settings
from linguini.db import Database, ReadSession, run_migrations
from linguini.households.router import router as households_router
from linguini.web import mount_spa


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Migrate the database, open the engines, and close them on shutdown."""
    settings: Settings = app.state.settings
    await asyncio.to_thread(run_migrations, settings.database_path)
    app.state.db = Database(settings.database_path)
    app.state.http = httpx.AsyncClient()
    app.state.jwks = JwksCache(app.state.http)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.db.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application; tests pass their own settings.

    Returns:
        The configured FastAPI app.
    """
    settings = settings or get_settings()
    app = FastAPI(title="Linguini", lifespan=lifespan, docs_url="/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CsrfMiddleware, settings=settings)

    @app.get("/api/health", tags=["meta"])
    async def health(session: ReadSession) -> dict[str, str]:
        await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/config", tags=["meta"])
    async def config(settings: Annotated[Settings, Depends(current_settings)]) -> dict[str, object]:
        return {
            "providers": {"google": settings.google_enabled, "apple": settings.apple_enabled},
            "locale": settings.locale,
        }

    app.include_router(auth_router)
    app.include_router(households_router)
    mount_spa(app, settings.static_dir)
    return app


def current_settings(request: Request) -> Settings:
    """Dependency returning the settings the app was built with.

    Returns:
        The app's settings.
    """
    return request.app.state.settings
