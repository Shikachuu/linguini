"""Pieces shared by every authorization-code flow: PKCE, state rows, JWKS verification."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from linguini.db import utcnow
from linguini.models import OAuthIntent, OAuthState

STATE_TTL = timedelta(minutes=10)
JWKS_TTL = timedelta(hours=6)
JWKS_MIN_REFRESH = timedelta(seconds=60)
log = logging.getLogger(__name__)


def random_token(nbytes: int = 32) -> str:
    """Return a URL-safe random string.

    Returns:
        ``nbytes`` of randomness, base64url encoded without padding.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode()


def sha256_b64url(value: str) -> str:
    """Return the base64url SHA-256 of ``value`` as used by PKCE S256.

    Returns:
        The unpadded base64url digest.
    """
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).rstrip(b"=").decode()


def sha256_hex(value: str) -> str:
    """Return the hex SHA-256 of ``value``.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_pair() -> tuple[str, str]:
    """Return a PKCE verifier and its S256 challenge.

    Returns:
        ``(code_verifier, code_challenge)``.
    """
    verifier = random_token(48)
    return verifier, sha256_b64url(verifier)


async def new_state(
    session: AsyncSession,
    *,
    provider: str,
    intent: OAuthIntent,
    nonce: str | None = None,
    code_verifier: str | None = None,
    binding_hash: str | None = None,
    invite_code: str | None = None,
    household_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    return_to: str | None = None,
) -> OAuthState:
    """Insert a pending flow row.

    Returns:
        The stored state row, with ``state`` set to a fresh random value.
    """
    await session.execute(delete(OAuthState).where(col(OAuthState.expires_at) < utcnow()))
    row = OAuthState(
        state=random_token(24),
        expires_at=utcnow() + STATE_TTL,
        provider=provider,
        intent=intent,
        nonce=nonce,
        code_verifier=code_verifier,
        binding_hash=binding_hash,
        invite_code=invite_code,
        household_id=household_id,
        user_id=user_id,
        return_to=return_to,
    )
    session.add(row)
    await session.flush()
    return row


async def consume_state(session: AsyncSession, state: str, provider: str, intent: OAuthIntent) -> OAuthState:
    """Load and delete a state row, failing on unknown, expired, or mismatched rows.

    Returns:
        The consumed row.

    Raises:
        HTTPException: 400 when the state is not usable.
    """
    row = await session.get(OAuthState, state)
    if row is None or row.provider != provider or row.intent != intent or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired login state")
    await session.delete(row)
    await session.flush()
    return row


def check_binding(row: OAuthState, cookie_value: str | None) -> None:
    """Confirm the browser finishing the flow is the one that started it.

    Raises:
        HTTPException: 400 when the binding cookie is missing or wrong.
    """
    if row.binding_hash is None:
        return
    if cookie_value is None or sha256_hex(cookie_value) != row.binding_hash:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login was started in a different browser")


class JwksCache:
    """Fetches a provider's signing keys over httpx and caches them by ``kid``."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Share one HTTP client across providers."""
        self._client = client
        self._sets: dict[str, tuple[jwt.PyJWKSet, datetime, datetime]] = {}
        self._lock = asyncio.Lock()

    async def key(self, jwks_url: str, kid: str) -> jwt.PyJWK:
        """Return the key with ``kid``, refetching at most once a minute if it is unknown.

        Returns:
            The matching key.

        Raises:
            HTTPException: 401 when no such key exists.
        """
        cached = self._sets.get(jwks_url)
        if cached is None or cached[1] < utcnow():
            cached = await self._refresh(jwks_url)
        try:
            return cached[0][kid]
        except KeyError:
            cached = await self._refresh(jwks_url)
        try:
            return cached[0][kid]
        except KeyError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown signing key") from exc

    async def _refresh(self, jwks_url: str) -> tuple[jwt.PyJWKSet, datetime, datetime]:
        async with self._lock:
            cached = self._sets.get(jwks_url)
            if cached is not None and cached[2] > utcnow():
                return cached
            response = await self._client.get(jwks_url, timeout=10)
            response.raise_for_status()
            now = utcnow()
            entry = (jwt.PyJWKSet.from_dict(response.json()), now + JWKS_TTL, now + JWKS_MIN_REFRESH)
            self._sets[jwks_url] = entry
            return entry


async def verify_id_token(
    jwks: JwksCache, token: str, *, jwks_url: str, issuers: list[str], audiences: list[str], algorithms: list[str]
) -> dict[str, Any]:
    """Verify an OIDC id_token signature and standard claims.

    Returns:
        The decoded claims.

    Raises:
        HTTPException: 401 when the token is invalid.
    """
    try:
        kid = jwt.get_unverified_header(token).get("kid", "")
        key = await jwks.key(jwks_url, kid)
        return jwt.decode(token, key, algorithms=algorithms, audience=audiences, issuer=issuers, leeway=60)
    except jwt.PyJWTError as exc:
        log.warning("id_token rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid id_token") from exc


async def exchange_code(client: httpx.AsyncClient, token_url: str, data: dict[str, str]) -> dict[str, Any]:
    """POST an authorization code to a token endpoint.

    Returns:
        The token response body.

    Raises:
        HTTPException: 401 when the provider rejects the code.
    """
    response = await client.post(token_url, data=data, headers={"Accept": "application/json"}, timeout=15)
    if response.status_code != status.HTTP_200_OK:
        log.warning("token exchange at %s failed: %s %s", token_url, response.status_code, response.text[:200])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token exchange failed")
    return response.json()
