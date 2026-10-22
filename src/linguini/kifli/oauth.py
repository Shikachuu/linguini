"""OAuth 2.1 client for the Kifli MCP server: discovery, registration, PKCE, refresh."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import HTTPException, status

from linguini.auth.crypto import decrypt, encrypt
from linguini.config import Settings
from linguini.db import Database, utcnow
from linguini.models import KifliClient, KifliConnection

REDIRECT_URI = "http://localhost:3334/oauth/callback"
GRANT_ERRORS = frozenset({"invalid_grant", "invalid_client", "unauthorized_client"})
STORED_REGISTRATION_KEYS = ("client_id", "client_id_issued_at", "redirect_uris", "grant_types", "scope")
SCOPE = "openid email roles offline_access"
REFRESH_MARGIN = timedelta(seconds=60)
log = logging.getLogger(__name__)

_discoveries: dict[str, Discovery] = {}
_refresh_locks: dict[uuid.UUID, asyncio.Lock] = {}


class ShopUnavailableError(Exception):
    """The shop's servers could not be reached or answered with a server error."""


class InvalidGrantError(Exception):
    """The shop rejected our credentials for good; the user must reconnect."""


@dataclass(frozen=True, slots=True)
class Discovery:
    """Endpoints learned from the protected-resource and authorization-server metadata."""

    resource: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str


async def discover(http: httpx.AsyncClient, mcp_url: str) -> Discovery:
    """Resolve the MCP server's authorization server and its endpoints, cached per URL.

    Returns:
        The endpoints.

    Raises:
        HTTPException: 502 when the metadata cannot be fetched.
    """
    cached = _discoveries.get(mcp_url)
    if cached is not None:
        return cached
    parts = urlsplit(mcp_url)
    resource_url = f"{parts.scheme}://{parts.netloc}/.well-known/oauth-protected-resource{parts.path}"
    try:
        resource = (await http.get(resource_url, timeout=15)).raise_for_status().json()
        issuer = str(resource["authorization_servers"][0]).rstrip("/")
        server = (
            (await http.get(f"{issuer}/.well-known/oauth-authorization-server", timeout=15)).raise_for_status().json()
        )
        found = Discovery(
            resource=str(resource.get("resource") or mcp_url),
            issuer=issuer,
            authorization_endpoint=server["authorization_endpoint"],
            token_endpoint=server["token_endpoint"],
            registration_endpoint=server["registration_endpoint"],
        )
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        log.warning("kifli discovery failed for %s: %s", mcp_url, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not read the shop's OAuth metadata") from exc
    _discoveries[mcp_url] = found
    return found


async def ensure_client(db: Database, http: httpx.AsyncClient, discovery: Discovery) -> KifliClient:
    """Return the dynamically registered client for the issuer, registering it on first use.

    Returns:
        The stored client.

    Raises:
        HTTPException: 502 when registration fails.
    """
    async with db.read_session() as session:
        existing = await session.get(KifliClient, discovery.issuer)
    if existing is not None:
        return existing
    body = {
        "client_name": "Linguini",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }
    response = await http.post(discovery.registration_endpoint, json=body, timeout=20)
    if response.status_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
        log.warning("kifli registration failed: %s %s", response.status_code, response.text[:200])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not register with the shop's identity server")
    registration = response.json()
    client = KifliClient(
        issuer=discovery.issuer,
        client_id=str(registration["client_id"]),
        registration={k: registration[k] for k in STORED_REGISTRATION_KEYS if k in registration},
        redirect_uris=[REDIRECT_URI],
        paste_only=True,
    )
    async with db.write_lock, db.write_session() as session:
        if (existing := await session.get(KifliClient, discovery.issuer)) is None:
            session.add(client)
            await session.commit()
            return client
        return existing


def authorize_url(discovery: Discovery, client_id: str, *, state: str, code_challenge: str) -> str:
    """Build the URL the user opens to sign in to the shop.

    Returns:
        The authorization URL.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": discovery.resource,
    }
    return f"{discovery.authorization_endpoint}?{urlencode(params)}"


def parse_callback_url(value: str) -> tuple[str, str]:
    """Extract ``code`` and ``state`` from the localhost URL the browser ended up on.

    Returns:
        ``(code, state)``.

    Raises:
        HTTPException: 422 when the pasted text is not a callback URL with both values.
    """
    query = parse_qs(urlsplit(value.strip()).query)
    code = query.get("code", [""])[0]
    state = query.get("state", [""])[0]
    if not code or not state:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Paste the full URL containing code and state")
    return code, state


async def exchange_code(
    http: httpx.AsyncClient, discovery: Discovery, client_id: str, *, code: str, code_verifier: str
) -> dict[str, Any]:
    """Trade the authorization code for tokens.

    Returns:
        The token response; ``InvalidGrantError`` or ``ShopUnavailableError`` propagate from the request.
    """
    return await _token_request(
        http,
        discovery,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": REDIRECT_URI,
            "resource": discovery.resource,
        },
    )


async def refresh_tokens(
    http: httpx.AsyncClient, discovery: Discovery, client_id: str, *, refresh_token: str
) -> dict[str, Any]:
    """Use a refresh token to get a new access token.

    Returns:
        The token response; ``InvalidGrantError`` or ``ShopUnavailableError`` propagate from the request.
    """
    return await _token_request(
        http,
        discovery,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "resource": discovery.resource,
        },
    )


async def _token_request(http: httpx.AsyncClient, discovery: Discovery, data: dict[str, str]) -> dict[str, Any]:
    try:
        response = await http.post(
            discovery.token_endpoint, data=data, headers={"Accept": "application/json"}, timeout=20
        )
    except httpx.HTTPError as exc:
        log.warning("kifli token request failed: %s", exc)
        raise ShopUnavailableError from exc
    if response.status_code == status.HTTP_200_OK:
        return response.json()
    log.warning("kifli token request rejected: %s %s", response.status_code, response.text[:200])
    if response.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED}:
        try:
            error = str(response.json().get("error", ""))
        except ValueError:
            error = ""
        if error in GRANT_ERRORS:
            raise InvalidGrantError(error)
    raise ShopUnavailableError(str(response.status_code))


def store_tokens(settings: Settings, connection: KifliConnection, tokens: dict[str, Any]) -> None:
    """Write a token response into a connection row, encrypted."""
    connection.access_token_enc = encrypt(settings, str(tokens["access_token"]))
    refresh = tokens.get("refresh_token")
    if isinstance(refresh, str) and refresh:
        connection.refresh_token_enc = encrypt(settings, refresh)
    expires_in = int(tokens.get("expires_in") or 3600)
    connection.expires_at = utcnow() + timedelta(seconds=expires_in)
    connection.scope = str(tokens.get("scope") or connection.scope or "")
    connection.broken = False


@dataclass(slots=True)
class LiveConnection:
    """A usable access token for one household's shop."""

    mcp_url: str
    access_token: str


class ConnectionState(StrEnum):
    """Why a household has no usable token right now."""

    NOT_CONNECTED = "not_connected"
    BROKEN = "broken"
    UNAVAILABLE = "unavailable"


async def live_connection(
    db: Database, http: httpx.AsyncClient, settings: Settings, household_id: uuid.UUID
) -> LiveConnection | ConnectionState:
    """The household's access token, refreshed when about to expire.

    Only a rejected refresh token marks the connection broken; outages leave it as it is.

    Returns:
        A live connection, or the state explaining why there is none.
    """
    async with db.read_session() as session:
        connection = await session.get(KifliConnection, household_id)
    if connection is None:
        return ConnectionState.NOT_CONNECTED
    if connection.broken:
        return ConnectionState.BROKEN
    if connection.expires_at - REFRESH_MARGIN > utcnow():
        return LiveConnection(connection.mcp_url, decrypt(settings, connection.access_token_enc))
    lock = _refresh_locks.setdefault(household_id, asyncio.Lock())
    async with lock:
        return await _refresh_locked(db, http, settings, household_id)


async def _refresh_locked(
    db: Database, http: httpx.AsyncClient, settings: Settings, household_id: uuid.UUID
) -> LiveConnection | ConnectionState:
    async with db.read_session() as session:
        connection = await session.get(KifliConnection, household_id)
    if connection is None:
        return ConnectionState.NOT_CONNECTED
    if connection.broken:
        return ConnectionState.BROKEN
    if connection.expires_at - REFRESH_MARGIN > utcnow():
        return LiveConnection(connection.mcp_url, decrypt(settings, connection.access_token_enc))
    used_refresh = connection.refresh_token_enc
    if used_refresh is None:
        await _mark_broken(db, household_id, used_refresh)
        return ConnectionState.BROKEN
    try:
        discovery = await discover(http, connection.mcp_url)
        tokens = await refresh_tokens(
            http, discovery, connection.client_id, refresh_token=decrypt(settings, used_refresh)
        )
    except InvalidGrantError:
        await _mark_broken(db, household_id, used_refresh)
        return ConnectionState.BROKEN
    except ShopUnavailableError, HTTPException:
        return ConnectionState.UNAVAILABLE
    async with db.write_lock, db.write_session() as session:
        row = await session.get(KifliConnection, household_id)
        if row is None:
            return ConnectionState.NOT_CONNECTED
        if row.refresh_token_enc != used_refresh:
            return LiveConnection(row.mcp_url, decrypt(settings, row.access_token_enc))
        store_tokens(settings, row, tokens)
        await session.commit()
        return LiveConnection(row.mcp_url, decrypt(settings, row.access_token_enc))


async def _mark_broken(db: Database, household_id: uuid.UUID, used_refresh: str | None) -> None:
    async with db.write_lock, db.write_session() as session:
        row = await session.get(KifliConnection, household_id)
        if row is not None and row.refresh_token_enc == used_refresh:
            row.broken = True
            await session.commit()
