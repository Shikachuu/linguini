"""Household, membership, and invite operations."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from linguini.db import utcnow
from linguini.models import Household, Invite, Membership, User

INVITE_TTL = timedelta(days=7)


async def households_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Household]:
    """List the households a user belongs to.

    Returns:
        Households ordered by name.
    """
    result = await session.execute(
        select(Household)
        .join(Membership, col(Membership.household_id) == col(Household.id))
        .where(Membership.user_id == user_id)
        .order_by(col(Household.name))
    )
    return list(result.scalars())


async def create_household(session: AsyncSession, user_id: uuid.UUID, name: str) -> Household:
    """Create a household with the caller as its first member.

    Returns:
        The new household.
    """
    household = Household(name=name)
    session.add(household)
    await session.flush()
    session.add(Membership(user_id=user_id, household_id=household.id))
    await session.flush()
    return household


async def membership(session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
    """Return the membership row if the user belongs to the household.

    Returns:
        The membership or None.
    """
    return await session.get(Membership, (user_id, household_id))


async def require_member(session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID) -> Household:
    """Load a household the user belongs to.

    Returns:
        The household.

    Raises:
        HTTPException: 404 when the household does not exist or the user is not a member.
    """
    if await membership(session, household_id, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Household not found")
    household = await session.get(Household, household_id)
    if household is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Household not found")
    return household


async def members(session: AsyncSession, household_id: uuid.UUID) -> list[tuple[User, Membership]]:
    """List members with their join dates.

    Returns:
        ``(user, membership)`` pairs ordered by join date.
    """
    result = await session.execute(
        select(User, Membership)
        .join(Membership, col(Membership.user_id) == col(User.id))
        .where(Membership.household_id == household_id)
        .order_by(col(Membership.joined_at))
    )
    return [(u, m) for u, m in result.all()]


async def remove_member(session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Remove a member; the household is deleted when nobody is left.

    Returns:
        True when the household was deleted as a result.

    Raises:
        HTTPException: 404 when the user is not a member.
    """
    row = await membership(session, household_id, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member")
    await session.delete(row)
    await session.flush()
    remaining = await session.execute(select(Membership).where(Membership.household_id == household_id).limit(1))
    if remaining.first() is None:
        await delete_household(session, household_id)
        return True
    return False


async def delete_household(session: AsyncSession, household_id: uuid.UUID) -> None:
    """Delete a household and everything that belongs to it."""
    from linguini.models import (
        InventoryEvent,
        InventoryItem,
        KifliConnection,
        KifliImportedOrder,
        Recipe,
        Run,
        Thread,
    )

    threads = (await session.execute(select(Thread.id).where(Thread.household_id == household_id))).scalars().all()
    for model, column in (
        (InventoryEvent, InventoryEvent.household_id),
        (InventoryItem, InventoryItem.household_id),
        (Recipe, Recipe.household_id),
        (KifliConnection, KifliConnection.household_id),
        (KifliImportedOrder, KifliImportedOrder.household_id),
        (Invite, Invite.household_id),
        (Membership, Membership.household_id),
    ):
        for row in (await session.execute(select(model).where(column == household_id))).scalars():
            await session.delete(row)
    if threads:
        for run in (await session.execute(select(Run).where(col(Run.thread_id).in_(threads)))).scalars():
            await session.delete(run)
        for thread in (await session.execute(select(Thread).where(col(Thread.id).in_(threads)))).scalars():
            await session.delete(thread)
    household = await session.get(Household, household_id)
    if household is not None:
        await session.delete(household)
    await session.flush()


async def create_invite(session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID) -> Invite:
    """Mint a single-use invite code.

    Returns:
        The invite row.
    """
    invite = Invite(
        code=secrets.token_urlsafe(12),
        household_id=household_id,
        created_by=user_id,
        expires_at=utcnow() + INVITE_TTL,
    )
    session.add(invite)
    await session.flush()
    return invite


async def peek_invite(session: AsyncSession, code: str) -> Invite | None:
    """Return the invite if it is still usable.

    Returns:
        The invite, or None when unknown, used, or expired.
    """
    invite = await session.get(Invite, code)
    if invite is None or invite.used_at is not None or invite.expires_at < utcnow():
        return None
    return invite


async def accept_invite(session: AsyncSession, code: str, user_id: uuid.UUID) -> Household:
    """Join the invite's household and burn the code.

    Returns:
        The joined household.

    Raises:
        HTTPException: 404 when the invite is not usable.
    """
    invite = await peek_invite(session, code)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found or already used")
    invite.used_by = user_id
    invite.used_at = utcnow()
    if await membership(session, invite.household_id, user_id) is None:
        session.add(Membership(user_id=user_id, household_id=invite.household_id))
    await session.flush()
    household = await session.get(Household, invite.household_id)
    if household is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Household not found")
    return household
