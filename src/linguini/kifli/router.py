"""Connecting a household to its Kifli account."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from linguini.auth.oidc import consume_state, new_state, pkce_pair
from linguini.auth.sessions import CurrentAuth
from linguini.config import Settings
from linguini.db import Database, ReadSession, get_database, utcnow
from linguini.households.router import MemberHousehold
from linguini.kifli import oauth
from linguini.models import KifliConnection, OAuthIntent, OAuthState

router = APIRouter(prefix="/api/households/{household_id}/kifli", tags=["kifli"])

PROVIDER = "kifli"


class ConnectionOut(BaseModel):
    """Whether and how a household is connected."""

    connected: bool
    broken: bool = False
    mcp_url: str | None = None
    connected_at: datetime | None = None
    expires_at: datetime | None = None


class ConnectOut(BaseModel):
    """What the user must do to finish connecting."""

    authorize_url: str
    redirect_uri: str
    instructions: str


class CallbackIn(BaseModel):
    """The URL the browser landed on after signing in."""

    callback_url: str


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


@router.get("")
async def connection_status(household: MemberHousehold, session: ReadSession) -> ConnectionOut:
    """Report the household's Kifli connection."""
    row = await session.get(KifliConnection, household.id)
    if row is None:
        return ConnectionOut(connected=False)
    return ConnectionOut(
        connected=True, broken=row.broken, mcp_url=row.mcp_url, connected_at=row.connected_at, expires_at=row.expires_at
    )


@router.post("/connect")
async def connect(
    household: MemberHousehold, request: Request, db: Annotated[Database, Depends(get_database)]
) -> ConnectOut:
    """Start the shop login; the user finishes it by pasting the callback URL."""
    settings = _settings(request)
    mcp_url = str(settings.kifli_mcp_url)
    discovery = await oauth.discover(_http(request), mcp_url)
    client = await oauth.ensure_client(db, _http(request), discovery)
    verifier, challenge = pkce_pair()
    async with db.write_lock, db.write_session() as session:
        row = await new_state(
            session,
            provider=PROVIDER,
            intent=OAuthIntent.KIFLI,
            household_id=household.id,
            code_verifier=verifier,
            return_to=mcp_url,
        )
        await session.commit()
    url = oauth.authorize_url(discovery, client.client_id, state=row.state, code_challenge=challenge)
    return ConnectOut(
        authorize_url=url,
        redirect_uri=oauth.REDIRECT_URI,
        instructions=(
            "Open the link and sign in to your shop account. Afterwards the browser will try to open "
            f"{oauth.REDIRECT_URI}, which will not load; copy that whole address from the address bar "
            "and paste it here."
        ),
    )


@router.post("/callback")
async def finish(
    household: MemberHousehold,
    body: CallbackIn,
    auth: CurrentAuth,
    request: Request,
    db: Annotated[Database, Depends(get_database)],
) -> ConnectionOut:
    """Exchange the pasted callback for tokens and store them for the household.

    The state is consumed before the code is spent, so a second paste cannot exchange it again.

    Raises:
        HTTPException: 400 when the state is unknown, expired, or belongs to another household;
            401 when the shop rejects the code; 502 when the shop cannot be reached.
    """
    settings = _settings(request)
    code, state = oauth.parse_callback_url(body.callback_url)
    async with db.write_lock, db.write_session() as session:
        pending = await session.get(OAuthState, state)
        if pending is None or pending.provider != PROVIDER or pending.household_id != household.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired connection attempt")
        pending = await consume_state(session, state, PROVIDER, OAuthIntent.KIFLI)
        mcp_url = pending.return_to or str(settings.kifli_mcp_url)
        verifier = pending.code_verifier or ""
        await session.commit()
    discovery = await oauth.discover(_http(request), mcp_url)
    client = await oauth.ensure_client(db, _http(request), discovery)
    try:
        tokens = await oauth.exchange_code(
            _http(request), discovery, client.client_id, code=code, code_verifier=verifier
        )
    except oauth.InvalidGrantError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The shop rejected the login; start again") from exc
    except oauth.ShopUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The shop is unreachable; try again later") from exc
    async with db.write_lock, db.write_session() as session:
        row = await session.get(KifliConnection, household.id)
        if row is None:
            row = KifliConnection(
                household_id=household.id,
                mcp_url=mcp_url,
                issuer=discovery.issuer,
                client_id=client.client_id,
                access_token_enc="",
                expires_at=utcnow(),
                connected_by=auth.user.id,
            )
            session.add(row)
        row.mcp_url = mcp_url
        row.issuer = discovery.issuer
        row.client_id = client.client_id
        row.connected_by = auth.user.id
        oauth.store_tokens(settings, row, tokens)
        await session.commit()
        return ConnectionOut(
            connected=True, broken=False, mcp_url=row.mcp_url, connected_at=row.connected_at, expires_at=row.expires_at
        )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(household: MemberHousehold, db: Annotated[Database, Depends(get_database)]) -> Response:
    """Forget the household's shop tokens."""
    async with db.write_lock, db.write_session() as session:
        row = await session.get(KifliConnection, household.id)
        if row is not None:
            await session.delete(row)
            await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
