"""FastAPI application factory and lifespan."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.routing import APIRoute
from pydantic import BaseModel
from pydantic_ai.models import Model
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from linguini import observability
from linguini.auth.oidc import JwksCache
from linguini.auth.router import router as auth_router
from linguini.auth.sessions import CsrfMiddleware
from linguini.chat.agent import build_agent, build_model, build_summarizer
from linguini.chat.router import ThreadLocks
from linguini.chat.router import router as chat_router
from linguini.config import Settings, get_settings
from linguini.db import Database, ReadSession, run_migrations, utcnow
from linguini.households.router import router as households_router
from linguini.inventory.router import router as inventory_router
from linguini.kifli.router import router as kifli_router
from linguini.models import OAuthState, Run, RunStatus, Session
from linguini.recipes.router import router as recipes_router
from linguini.web import mount_spa


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Migrate the database, open the engines, and close them on shutdown."""
    settings: Settings = app.state.settings
    await asyncio.to_thread(run_migrations, settings.database_path)
    app.state.db = Database(settings.database_path)
    await app.state.db.run_write(fail_interrupted_runs)
    await app.state.db.run_write(sweep_expired)
    app.state.http = httpx.AsyncClient()
    app.state.jwks = JwksCache(app.state.http)
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.db.dispose()
        if app.state.tracer_provider is not None:
            await asyncio.to_thread(app.state.tracer_provider.shutdown)


class ProvidersOut(BaseModel):
    """Which login providers are configured."""

    google: bool
    apple: bool


class ConfigOut(BaseModel):
    """Public configuration the web app needs before login."""

    providers: ProvidersOut
    locale: str


def operation_id(route: APIRoute) -> str:
    """Name OpenAPI operations after their handler so generated clients stay readable.

    Returns:
        The route's handler name.
    """
    return route.name


async def fail_interrupted_runs(session: AsyncSession) -> None:
    """Runs still marked running at startup were cut off by a restart."""
    await session.execute(
        update(Run).where(col(Run.status) == RunStatus.RUNNING).values(status=RunStatus.FAILED, finished_at=utcnow())
    )


async def sweep_expired(session: AsyncSession) -> None:
    """Drop sessions and login states that can no longer be used."""
    now = utcnow()
    await session.execute(delete(Session).where(col(Session.expires_at) < now))
    await session.execute(delete(OAuthState).where(col(OAuthState.expires_at) < now))


def create_app(
    settings: Settings | None = None, model: Model | None = None, summary_model: Model | None = None
) -> FastAPI:
    """Build the application; tests pass their own settings and models.

    Returns:
        The configured FastAPI app.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="Linguini",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/api/openapi.json",
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    chat_model = model or build_model(settings)
    tracing = observability.configure(settings)
    app.state.tracer_provider = tracing[0] if tracing else None
    capabilities = [tracing[1]] if tracing else []
    app.state.agent = build_agent(chat_model, capabilities)
    app.state.summarizer = build_summarizer(summary_model or _summary_model(settings, chat_model), capabilities)
    app.state.thread_locks = ThreadLocks()
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CsrfMiddleware, settings=settings)

    @app.get("/api/health", tags=["meta"])
    async def health(session: ReadSession) -> dict[str, str]:
        await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/config", tags=["meta"])
    async def config(settings: Annotated[Settings, Depends(current_settings)]) -> ConfigOut:
        return ConfigOut(
            providers=ProvidersOut(google=settings.google_enabled, apple=settings.apple_enabled),
            locale=settings.locale,
        )

    app.include_router(auth_router)
    app.include_router(households_router)
    app.include_router(inventory_router)
    app.include_router(chat_router)
    app.include_router(recipes_router)
    app.include_router(kifli_router)
    mount_spa(app, settings.static_dir)
    return app


def _summary_model(settings: Settings, default: Model) -> Model:
    if settings.summary_model is None or settings.summary_model == settings.model:
        return default
    return build_model(settings.model_copy(update={"model": settings.summary_model}))


def current_settings(request: Request) -> Settings:
    """Dependency returning the settings the app was built with.

    Returns:
        The app's settings.
    """
    return request.app.state.settings
