"""Serve the built SPA next to the API."""

from __future__ import annotations

from pathlib import Path
from typing import override

from fastapi import FastAPI, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


class StaticCacheMiddleware(BaseHTTPMiddleware):
    """Cache-Control for SPA responses."""

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            return response
        response.headers["Cache-Control"] = IMMUTABLE if path.startswith("/assets/") else NO_CACHE
        return response


def mount_spa(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the SPA build, if any, behind the API routes."""

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(path: str) -> None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    if static_dir is None or not static_dir.is_dir():

        @app.get("/", include_in_schema=False)
        async def no_frontend() -> dict[str, str]:
            return {"detail": "No frontend build configured; API docs at /docs"}

        return

    app.add_middleware(StaticCacheMiddleware)
    app.frontend("/", directory=static_dir, fallback="index.html", check_dir=True)
