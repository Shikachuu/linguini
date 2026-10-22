"""Login, logout, and account endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from linguini.auth import accounts, apple, google
from linguini.auth.crypto import encrypt
from linguini.auth.oidc import (
    JwksCache,
    check_binding,
    consume_state,
    new_state,
    pkce_pair,
    random_token,
    sha256_hex,
)
from linguini.auth.sessions import (
    Auth,
    CurrentAuth,
    clear_session_cookie,
    create_session,
    current_auth,
    set_session_cookie,
)
from linguini.config import Settings
from linguini.db import Database, ReadSession, WriteSession, get_database, utcnow
from linguini.households import service as households
from linguini.models import ClientKind, Identity, OAuthIntent, OAuthState, Provider, Session, User

router = APIRouter(prefix="/api", tags=["auth"])

BINDING_COOKIE_SECURE = "__Host-oauth"
BINDING_COOKIE_PLAIN = "oauth"
BINDING_MAX_AGE = 600
NATIVE_PROVIDER = "native"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def _jwks(request: Request) -> JwksCache:
    return request.app.state.jwks


def _binding_cookie(settings: Settings) -> str:
    return BINDING_COOKIE_SECURE if settings.is_https else BINDING_COOKIE_PLAIN


def _redirect_uri(settings: Settings, provider: Provider) -> str:
    return f"{str(settings.public_url).rstrip('/')}/api/auth/{provider.value}/callback"


def _safe_return_to(value: str | None) -> str:
    if not value:
        return "/"
    parts = urlsplit(value.replace("\\", "/"))
    if parts.scheme or parts.netloc or not parts.path.startswith("/") or parts.path.startswith("//"):
        return "/"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "/"
    return value


def _provider(name: str, settings: Settings) -> Provider:
    try:
        provider = Provider(name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider") from exc
    enabled = settings.google_enabled if provider is Provider.GOOGLE else settings.apple_enabled
    if not enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{provider.value} login is not configured")
    return provider


async def optional_auth(request: Request, db: Annotated[Database, Depends(get_database)]) -> Auth | None:
    """Dependency: the caller if signed in, else None.

    Returns:
        The auth context or None.
    """
    try:
        return await current_auth(request, db)
    except HTTPException:
        return None


@router.get("/auth/{provider}/start", include_in_schema=False)
async def start(
    provider: str,
    request: Request,
    session: WriteSession,
    auth: Annotated[Auth | None, Depends(optional_auth)],
    invite: str | None = None,
    return_to: str | None = None,
) -> RedirectResponse:
    """Begin a browser login; a signed-in caller links a second provider instead."""
    settings = _settings(request)
    prov = _provider(provider, settings)
    binding = random_token(24)
    nonce = random_token(24)
    verifier, challenge = pkce_pair()
    row = await new_state(
        session,
        provider=prov.value,
        intent=OAuthIntent.LINK if auth else OAuthIntent.LOGIN,
        user_id=auth.user.id if auth else None,
        nonce=nonce,
        code_verifier=verifier,
        binding_hash=sha256_hex(binding),
        invite_code=invite,
        return_to=_safe_return_to(return_to),
    )
    redirect_uri = _redirect_uri(settings, prov)
    if prov is Provider.GOOGLE:
        url = google.authorize_url(
            settings, state=row.state, nonce=nonce, code_challenge=challenge, redirect_uri=redirect_uri
        )
    else:
        url = apple.authorize_url(settings, state=row.state, nonce=nonce, redirect_uri=redirect_uri)
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        _binding_cookie(settings),
        binding,
        max_age=BINDING_MAX_AGE,
        httponly=True,
        secure=settings.is_https,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/auth/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    db: Annotated[Database, Depends(get_database)],
    auth: Annotated[Auth | None, Depends(optional_auth)],
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish a Google login."""
    settings = _settings(request)
    if error or code is None:
        return _login_failed(error or "missing_code")
    pending = await _peek_state(db, state, Provider.GOOGLE)
    check_binding(pending, request.cookies.get(_binding_cookie(settings)))
    _check_link_owner(pending, auth)
    tokens = await google.exchange(
        _http(request),
        settings,
        code=code,
        code_verifier=pending.code_verifier or "",
        redirect_uri=_redirect_uri(settings, Provider.GOOGLE),
    )
    claims = await google.verify(_jwks(request), settings, tokens.get("id_token", ""))
    _check_nonce(claims, pending.nonce)
    return await _finish_browser_login(request, db, pending, claims, None, None)


@router.post("/auth/apple/callback", include_in_schema=False)
async def apple_callback(
    request: Request,
    session: WriteSession,
    state: Annotated[str, Form()],
    code: Annotated[str | None, Form()] = None,
    id_token: Annotated[str | None, Form()] = None,
    user: Annotated[str | None, Form()] = None,
    error: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """Receive Apple's cross-site form POST and bounce to a same-site GET.

    Raises:
        HTTPException: 400 when the state is unknown or expired.
    """
    if error or code is None:
        return _login_failed(error or "missing_code")
    row = await session.get(OAuthState, state)
    if row is None or row.provider != Provider.APPLE.value or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired login state")
    row.payload = {"code": code, "id_token": id_token, "user": user}
    await session.flush()
    return RedirectResponse(f"/api/auth/apple/finish?state={state}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/apple/finish", include_in_schema=False)
async def apple_finish(
    request: Request,
    db: Annotated[Database, Depends(get_database)],
    auth: Annotated[Auth | None, Depends(optional_auth)],
    state: str,
) -> RedirectResponse:
    """Finish an Apple login once the browser is back on our origin."""
    settings = _settings(request)
    pending = await _peek_state(db, state, Provider.APPLE)
    check_binding(pending, request.cookies.get(_binding_cookie(settings)))
    _check_link_owner(pending, auth)
    payload = pending.payload or {}
    client_id = settings.apple_services_id or ""
    tokens = await apple.exchange(
        _http(request),
        settings,
        code=str(payload.get("code") or ""),
        client_id=client_id,
        redirect_uri=_redirect_uri(settings, Provider.APPLE),
    )
    claims = await apple.verify(_jwks(request), settings, tokens.get("id_token", ""))
    _check_nonce(claims, pending.nonce)
    name, _ = apple.parse_user_field(payload.get("user"))
    refresh = tokens.get("refresh_token")
    enc = encrypt(settings, refresh) if isinstance(refresh, str) else None
    return await _finish_browser_login(request, db, pending, claims, name, enc)


class NonceOut(BaseModel):
    """A server-issued nonce for native sign-in."""

    nonce: str


@router.post("/auth/nonce")
async def issue_nonce(session: WriteSession) -> NonceOut:
    """Issue a nonce a native app must send to the provider and back to us."""
    row = await new_state(session, provider=NATIVE_PROVIDER, intent=OAuthIntent.LOGIN)
    row.nonce = row.state
    await session.flush()
    return NonceOut(nonce=row.state)


class NativeIn(BaseModel):
    """Native sign-in payload."""

    id_token: str
    nonce: str
    authorization_code: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    invite: str | None = None


class SessionOut(BaseModel):
    """A bearer session for native clients."""

    session_token: str
    expires_at: datetime


@router.post("/auth/{provider}/native")
async def native_login(
    provider: str, body: NativeIn, request: Request, db: Annotated[Database, Depends(get_database)]
) -> SessionOut:
    """Sign in with an id_token obtained by a native SDK.

    Raises:
        HTTPException: 400 when the nonce is unknown or expired.
    """
    settings = _settings(request)
    prov = _provider(provider, settings)
    async with db.read_session() as read:
        pending = await read.get(OAuthState, body.nonce)
    if pending is None or pending.provider != NATIVE_PROVIDER or pending.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired nonce")
    verify = google.verify if prov is Provider.GOOGLE else apple.verify
    claims = await verify(_jwks(request), settings, body.id_token)
    _check_nonce(claims, body.nonce, allow_hashed=prov is Provider.APPLE)
    enc = None
    if prov is Provider.APPLE and body.authorization_code:
        tokens = await apple.exchange(
            _http(request), settings, code=body.authorization_code, client_id=str(claims["aud"]), redirect_uri=None
        )
        refresh = tokens.get("refresh_token")
        enc = encrypt(settings, refresh) if isinstance(refresh, str) else None
    name = " ".join(p for p in (body.given_name, body.family_name) if p) or None
    async with db.write_lock, db.write_session() as session:
        await consume_state(session, body.nonce, NATIVE_PROVIDER, OAuthIntent.LOGIN)
        user = await accounts.sign_in(
            session, provider=prov, claims=claims, display_name=name, invite_code=body.invite, refresh_token_enc=enc
        )
        row, token = await create_session(
            session, settings, user.id, ClientKind.MOBILE, request.headers.get("user-agent")
        )
        await session.commit()
    return SessionOut(session_token=token, expires_at=row.expires_at)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: CurrentAuth, session: WriteSession, request: Request) -> Response:
    """End the current session."""
    row = await session.get(Session, auth.session.id)
    if row is not None:
        await session.delete(row)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, _settings(request))
    return response


class IdentityOut(BaseModel):
    """A linked provider."""

    provider: Provider
    email: str | None


class HouseholdRef(BaseModel):
    """A household the user belongs to."""

    id: uuid.UUID
    name: str


class MeOut(BaseModel):
    """The signed-in user."""

    id: uuid.UUID
    display_name: str
    identities: list[IdentityOut]
    households: list[HouseholdRef]


@router.get("/me")
async def me(auth: CurrentAuth, session: ReadSession) -> MeOut:
    """Describe the signed-in user."""
    idents = (await session.execute(select(Identity).where(Identity.user_id == auth.user.id))).scalars()
    hh = await households.households_for_user(session, auth.user.id)
    return MeOut(
        id=auth.user.id,
        display_name=auth.user.display_name,
        identities=[IdentityOut(provider=i.provider, email=i.email) for i in idents],
        households=[HouseholdRef(id=h.id, name=h.name) for h in hh],
    )


class NotificationIn(BaseModel):
    """Apple server-to-server notification envelope."""

    payload: str


@router.post("/auth/apple/notifications", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def apple_notifications(
    body: NotificationIn, request: Request, db: Annotated[Database, Depends(get_database)]
) -> Response:
    """Handle consent revocation and account deletion pushed by Apple."""
    settings = _settings(request)
    events = await apple.decode_notification(_jwks(request), settings, body.payload)
    kind = events.get("type")
    sub = str(events.get("sub") or "")
    if kind not in {"consent-revoked", "account-deleted"} or not sub:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    async with db.write_lock, db.write_session() as session:
        result = await session.execute(
            select(Identity).where(Identity.provider == Provider.APPLE, Identity.subject == sub)
        )
        identity = result.scalar_one_or_none()
        if identity is not None:
            await _drop_identity(session, identity)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _drop_identity(session: AsyncSession, identity: Identity) -> None:
    user_id = identity.user_id
    await session.delete(identity)
    await session.flush()
    remaining = (await session.execute(select(Identity).where(Identity.user_id == user_id).limit(1))).first()
    if remaining is None:
        for row in (await session.execute(select(Session).where(Session.user_id == user_id))).scalars():
            await session.delete(row)
        user = await session.get(User, user_id)
        if user is not None:
            user.deleted_at = utcnow()
    await session.flush()


async def _peek_state(db: Database, state: str, provider: Provider) -> OAuthState:
    async with db.read_session() as read:
        row = await read.get(OAuthState, state)
    if row is None or row.provider != provider.value or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired login state")
    return row


def _check_link_owner(pending: OAuthState, auth: Auth | None) -> None:
    if pending.intent is OAuthIntent.LINK and (auth is None or auth.user.id != pending.user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sign in again before linking a provider")


def _check_nonce(claims: dict[str, Any], expected: str | None, *, allow_hashed: bool = False) -> None:
    got = str(claims.get("nonce") or "")
    accepted = {expected, sha256_hex(expected)} if allow_hashed and expected else {expected}
    if expected is None or got not in accepted:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nonce mismatch")


def _login_failed(reason: str) -> RedirectResponse:
    return RedirectResponse(f"/?{urlencode({'login_error': reason[:64]})}", status_code=status.HTTP_303_SEE_OTHER)


async def _finish_browser_login(
    request: Request,
    db: Database,
    peeked: OAuthState,
    claims: dict[str, Any],
    display_name: str | None,
    refresh_token_enc: str | None,
) -> RedirectResponse:
    settings = _settings(request)
    provider = Provider(peeked.provider)
    async with db.write_lock, db.write_session() as session:
        pending = await consume_state(session, peeked.state, provider.value, peeked.intent)
        linking = pending.intent is OAuthIntent.LINK
        user = await accounts.sign_in(
            session,
            provider=provider,
            claims=claims,
            display_name=display_name,
            invite_code=None if linking else pending.invite_code,
            link_to=pending.user_id if linking else None,
            refresh_token_enc=refresh_token_enc,
        )
        if pending.intent is OAuthIntent.LINK:
            await session.commit()
            return RedirectResponse(pending.return_to or "/", status_code=status.HTTP_303_SEE_OTHER)
        _, token = await create_session(session, settings, user.id, ClientKind.WEB, request.headers.get("user-agent"))
        await session.commit()
    response = RedirectResponse(pending.return_to or "/", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, settings, token, settings.session_ttl_days * 86400)
    response.delete_cookie(_binding_cookie(settings), path="/")
    return response
