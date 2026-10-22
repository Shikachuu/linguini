"""Opaque server-side sessions carried by a cookie (web) or a bearer header (mobile)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from starlette.types import ASGIApp, Receive, Scope, Send

from linguini.config import Settings
from linguini.db import Database, get_database, utcnow
from linguini.models import ClientKind, Session, User

SECURE_COOKIE = "__Host-sid"
PLAIN_COOKIE = "sid"
CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "linguini"
CSRF_EXEMPT = frozenset({"/api/auth/apple/callback", "/api/auth/apple/notifications"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LAST_SEEN_REFRESH = timedelta(hours=1)


def cookie_name(settings: Settings) -> str:
    """Return the session cookie name; the ``__Host-`` prefix needs HTTPS.

    Returns:
        The cookie name for this deployment.
    """
    return SECURE_COOKIE if settings.is_https else PLAIN_COOKIE


def mint_token() -> str:
    """Return a fresh random session token.

    Returns:
        A URL-safe token with 256 bits of entropy.
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage.

    Returns:
        Hex SHA-256 of the token.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def set_session_cookie(response: Response, settings: Settings, token: str, max_age: int) -> None:
    """Attach the session cookie to a response."""
    response.set_cookie(
        cookie_name(settings),
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.is_https,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Expire the session cookie."""
    response.delete_cookie(cookie_name(settings), path="/", httponly=True, secure=settings.is_https, samesite="lax")


async def create_session(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, client_kind: ClientKind, user_agent: str | None
) -> tuple[Session, str]:
    """Insert a session row and return it with the plaintext token.

    Returns:
        The stored row and the token to hand to the client.
    """
    token = mint_token()
    row = Session(
        token_hash=hash_token(token),
        user_id=user_id,
        client_kind=client_kind,
        expires_at=utcnow() + timedelta(days=settings.session_ttl_days),
        user_agent=(user_agent or "")[:200] or None,
    )
    session.add(row)
    await session.flush()
    return row, token


@dataclass(slots=True)
class Auth:
    """The authenticated caller."""

    user: User
    session: Session
    via_cookie: bool


def _token_from_request(request: Request, settings: Settings) -> tuple[str, bool] | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip(), False
    cookie = request.cookies.get(cookie_name(settings))
    if cookie:
        return cookie, True
    return None


async def current_auth(request: Request, db: Annotated[Database, Depends(get_database)]) -> Auth:
    """Resolve the session from the bearer header or the cookie.

    Returns:
        The caller's user and session.

    Raises:
        HTTPException: 401 when no valid session is presented.
    """
    settings: Settings = request.app.state.settings
    found = _token_from_request(request, settings)
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    token, via_cookie = found
    now = utcnow()
    async with db.read_session() as read:
        result = await read.execute(
            select(Session, User)
            .join(User, col(User.id) == col(Session.user_id))
            .where(Session.token_hash == hash_token(token), Session.expires_at > now, col(User.deleted_at).is_(None))
        )
        pair = result.first()
    if pair is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    row, user = pair
    idle_limit = row.last_seen_at + timedelta(days=settings.session_idle_days)
    if idle_limit < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session idle too long")
    if now - row.last_seen_at > LAST_SEEN_REFRESH:
        db.write_later(_touch(row.id, now))
    return Auth(user=user, session=row, via_cookie=via_cookie)


def _touch(session_id: uuid.UUID, now: datetime) -> Callable[[AsyncSession], Awaitable[None]]:
    async def work(write: AsyncSession) -> None:
        fresh = await write.get(Session, session_id)
        if fresh is not None:
            fresh.last_seen_at = now

    return work


CurrentAuth = Annotated[Auth, Depends(current_auth)]


class CsrfMiddleware:
    """Reject cookie-authenticated unsafe requests that do not prove same-origin intent."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        """Remember the app and the origin that counts as ours."""
        self.app = app
        self.settings = settings
        parts = urlsplit(str(settings.public_url))
        self.origin = f"{parts.scheme}://{parts.netloc}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the check, then the app."""
        if scope["type"] != "http" or not self._needs_check(scope):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        if self._is_trusted(headers):
            await self.app(scope, receive, send)
            return
        response = _forbidden()
        await response(scope, receive, send)

    def _needs_check(self, scope: Scope) -> bool:
        path: str = scope["path"]
        if scope["method"] in SAFE_METHODS or not path.startswith("/api/") or path in CSRF_EXEMPT:
            return False
        headers = dict(scope["headers"])
        if headers.get(b"authorization", b"").lower().startswith(b"bearer "):
            return False
        cookies = SimpleCookie()
        cookies.load(headers.get(b"cookie", b"").decode())
        return cookie_name(self.settings) in cookies

    def _is_trusted(self, headers: dict[str, str]) -> bool:
        if not hmac.compare_digest(headers.get(CSRF_HEADER, ""), CSRF_HEADER_VALUE):
            return False
        fetch_site = headers.get("sec-fetch-site")
        if fetch_site is not None:
            return fetch_site == "same-origin"
        return headers.get("origin", "") == self.origin


def _forbidden() -> Response:
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": "Cross-site request rejected"}, status_code=status.HTTP_403_FORBIDDEN)
