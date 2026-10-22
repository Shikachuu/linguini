"""Turning verified provider claims into users and identities."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from linguini.db import utcnow
from linguini.households import service as households
from linguini.models import Identity, Provider, User


def display_name_from(claims: dict[str, Any], provided: str | None) -> str:
    """Pick a display name from the provider's one-time name, the claims, or the email.

    Returns:
        A non-empty display name.
    """
    if provided:
        return provided[:80]
    for key in ("name", "given_name"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    email = claims.get("email")
    if isinstance(email, str) and "@" in email:
        return email.split("@", 1)[0][:80]
    return "Someone"


async def sign_in(
    session: AsyncSession,
    *,
    provider: Provider,
    claims: dict[str, Any],
    display_name: str | None = None,
    invite_code: str | None = None,
    link_to: uuid.UUID | None = None,
    refresh_token_enc: str | None = None,
) -> User:
    """Resolve the identity to a user, creating or linking as the rules allow.

    Returns:
        The signed-in user.

    Raises:
        HTTPException: 403 when a new account needs an invite, 409 on a conflicting link.
    """
    subject = str(claims["sub"])
    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    result = await session.execute(select(Identity).where(Identity.provider == provider, Identity.subject == subject))
    identity = result.scalar_one_or_none()

    if link_to is not None:
        if identity is not None and identity.user_id != link_to:
            raise HTTPException(status.HTTP_409_CONFLICT, "That account is already linked to another user")
        if identity is None:
            identity = _new_identity(link_to, provider, subject, claims, refresh_token_enc)
            session.add(identity)
        user = await session.get(User, link_to)
        if user is None or user.deleted_at is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deleted")
    elif identity is not None:
        identity.last_login_at = utcnow()
        identity.email = email or identity.email
        if refresh_token_enc:
            identity.apple_refresh_token_enc = refresh_token_enc
        user = await session.get(User, identity.user_id)
        if user is None or user.deleted_at is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deleted")
    else:
        user = await _create_user(session, claims, display_name, invite_code)
        session.add(_new_identity(user.id, provider, subject, claims, refresh_token_enc))

    if user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not found")
    if invite_code and await households.peek_invite(session, invite_code) is not None:
        await households.accept_invite(session, invite_code, user.id)
    await session.flush()
    return user


async def _create_user(
    session: AsyncSession, claims: dict[str, Any], display_name: str | None, invite_code: str | None
) -> User:
    count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    if count > 0 and (invite_code is None or await households.peek_invite(session, invite_code) is None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invite_required")
    user = User(display_name=display_name_from(claims, display_name))
    session.add(user)
    await session.flush()
    return user


def _new_identity(
    user_id: uuid.UUID, provider: Provider, subject: str, claims: dict[str, Any], refresh_token_enc: str | None
) -> Identity:
    return Identity(
        user_id=user_id,
        provider=provider,
        subject=subject,
        email=claims.get("email") if isinstance(claims.get("email"), str) else None,
        email_verified=bool(claims.get("email_verified")),
        is_private_email=bool(claims.get("is_private_email")),
        apple_refresh_token_enc=refresh_token_enc,
    )
