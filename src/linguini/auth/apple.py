"""Sign in with Apple: form_post callback, self-signed client secret, revocation, notifications."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from linguini.auth.oidc import JwksCache, exchange_code, verify_id_token
from linguini.config import Settings
from linguini.db import utcnow

AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"
TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"
JWKS_URL = "https://appleid.apple.com/auth/keys"
ISSUER = "https://appleid.apple.com"
SCOPE = "name email"
SECRET_TTL = timedelta(hours=1)

_secret_cache: dict[str, tuple[str, Any]] = {}


def client_secret(settings: Settings, client_id: str) -> str:
    """Return an ES256 client-secret JWT for ``client_id``, cached until shortly before expiry.

    Returns:
        The signed JWT.
    """
    cache_key = f"{settings.apple_team_id}:{settings.apple_key_id}:{client_id}"
    cached = _secret_cache.get(cache_key)
    now = utcnow()
    if cached is not None and cached[1] > now + timedelta(minutes=5):
        return cached[0]
    key = settings.apple_private_key.get_secret_value() if settings.apple_private_key else ""
    expires = now + SECRET_TTL
    token = jwt.encode(
        {"iss": settings.apple_team_id, "iat": now, "exp": expires, "aud": ISSUER, "sub": client_id},
        key,
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )
    _secret_cache[cache_key] = (token, expires)
    return token


def authorize_url(settings: Settings, *, state: str, nonce: str, redirect_uri: str) -> str:
    """Build the Apple authorization URL; scopes force ``response_mode=form_post``.

    Returns:
        The URL to redirect the browser to.
    """
    params = {
        "client_id": settings.apple_services_id or "",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "form_post",
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange(
    client: httpx.AsyncClient, settings: Settings, *, code: str, client_id: str, redirect_uri: str | None
) -> dict[str, Any]:
    """Trade the code for tokens; ``client_id`` is the Services ID on web and the bundle id on iOS.

    Returns:
        The token response, including ``id_token`` and ``refresh_token``.
    """
    data = {
        "client_id": client_id,
        "client_secret": client_secret(settings, client_id),
        "code": code,
        "grant_type": "authorization_code",
    }
    if redirect_uri:
        data["redirect_uri"] = redirect_uri
    return await exchange_code(client, TOKEN_URL, data)


async def revoke(client: httpx.AsyncClient, settings: Settings, *, refresh_token: str, client_id: str) -> None:
    """Revoke a refresh token so Apple forgets the authorization.

    ``client_id`` must be the one the token was issued to (Services ID on web, bundle id on iOS).
    """
    response = await client.post(
        REVOKE_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret(settings, client_id),
            "token": refresh_token,
            "token_type_hint": "refresh_token",
        },
        timeout=15,
    )
    response.raise_for_status()


def audiences(settings: Settings) -> list[str]:
    """Return every client id whose tokens we accept.

    Returns:
        Services ID plus bundle ids.
    """
    return [a for a in [settings.apple_services_id, *settings.apple_bundle_ids] if a]


async def verify(jwks: JwksCache, settings: Settings, id_token: str) -> dict[str, Any]:
    """Verify an Apple id_token.

    Returns:
        The claims; boolean claims that Apple sends as strings are normalized.
    """
    claims = await verify_id_token(
        jwks, id_token, jwks_url=JWKS_URL, issuers=[ISSUER], audiences=audiences(settings), algorithms=["RS256"]
    )
    for key in ("email_verified", "is_private_email"):
        if key in claims:
            claims[key] = str(claims[key]).lower() == "true"
    return claims


def parse_user_field(raw: str | None) -> tuple[str | None, str | None]:
    """Parse the one-time ``user`` form field into (display name, email).

    Returns:
        Name joined from first and last name, and the email, either may be None.
    """
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
    except ValueError:
        return None, None
    name = data.get("name") or {}
    parts = [str(name.get("firstName") or "").strip(), str(name.get("lastName") or "").strip()]
    display = " ".join(p for p in parts if p) or None
    return display, data.get("email")


async def decode_notification(jwks: JwksCache, settings: Settings, payload: str) -> dict[str, Any]:
    """Verify a server-to-server notification JWT and return its ``events`` object.

    Returns:
        The decoded events, with ``type`` and ``sub``.
    """
    claims = await verify_id_token(
        jwks, payload, jwks_url=JWKS_URL, issuers=[ISSUER], audiences=audiences(settings), algorithms=["RS256"]
    )
    events = claims.get("events", {})
    return json.loads(events) if isinstance(events, str) else events
