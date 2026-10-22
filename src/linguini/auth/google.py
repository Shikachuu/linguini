"""Google OpenID Connect with the authorization-code flow and PKCE."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from linguini.auth.oidc import JwksCache, exchange_code, verify_id_token
from linguini.config import Settings

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
SCOPE = "openid email profile"


def authorize_url(settings: Settings, *, state: str, nonce: str, code_challenge: str, redirect_uri: str) -> str:
    """Build the Google authorization URL.

    Returns:
        The URL to redirect the browser to.
    """
    params = {
        "client_id": settings.google_client_id or "",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange(
    client: httpx.AsyncClient, settings: Settings, *, code: str, code_verifier: str, redirect_uri: str
) -> dict[str, Any]:
    """Trade the code for tokens.

    Returns:
        The token response, including ``id_token``.
    """
    secret = settings.google_client_secret.get_secret_value() if settings.google_client_secret else ""
    return await exchange_code(
        client,
        TOKEN_URL,
        {
            "client_id": settings.google_client_id or "",
            "client_secret": secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )


def audiences(settings: Settings) -> list[str]:
    """Return every client id whose tokens we accept.

    Returns:
        Web client id plus mobile client ids.
    """
    return [a for a in [settings.google_client_id, *settings.google_extra_audiences] if a]


async def verify(jwks: JwksCache, settings: Settings, id_token: str) -> dict[str, Any]:
    """Verify a Google id_token.

    Returns:
        The claims.
    """
    return await verify_id_token(
        jwks, id_token, jwks_url=JWKS_URL, issuers=ISSUERS, audiences=audiences(settings), algorithms=["RS256"]
    )
