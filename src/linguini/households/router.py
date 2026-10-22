"""Household endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from linguini.auth.sessions import CurrentAuth
from linguini.db import ReadSession, WriteSession
from linguini.households import service
from linguini.models import Household

router = APIRouter(prefix="/api", tags=["households"])


class HouseholdIn(BaseModel):
    """Create or rename payload."""

    name: str = Field(min_length=1, max_length=80)


class HouseholdOut(BaseModel):
    """A household as returned to clients."""

    id: uuid.UUID
    name: str
    created_at: datetime


class MemberOut(BaseModel):
    """A member of a household."""

    user_id: uuid.UUID
    display_name: str
    joined_at: datetime


class InviteOut(BaseModel):
    """A freshly minted invite."""

    code: str
    url: str
    expires_at: datetime


async def household_member(household_id: uuid.UUID, auth: CurrentAuth, session: ReadSession) -> Household:
    """Dependency: the household from the path, only if the caller is a member.

    Returns:
        The household.
    """
    return await service.require_member(session, household_id, auth.user.id)


MemberHousehold = Annotated[Household, Depends(household_member)]


@router.get("/households")
async def list_households(auth: CurrentAuth, session: ReadSession) -> list[HouseholdOut]:
    """List the caller's households."""
    rows = await service.households_for_user(session, auth.user.id)
    return [HouseholdOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/households", status_code=status.HTTP_201_CREATED)
async def create_household(body: HouseholdIn, auth: CurrentAuth, session: WriteSession) -> HouseholdOut:
    """Create a household with the caller as its first member."""
    row = await service.create_household(session, auth.user.id, body.name)
    return HouseholdOut.model_validate(row, from_attributes=True)


@router.get("/households/{household_id}")
async def get_household(household: MemberHousehold) -> HouseholdOut:
    """Return one household."""
    return HouseholdOut.model_validate(household, from_attributes=True)


@router.patch("/households/{household_id}")
async def rename_household(household: MemberHousehold, body: HouseholdIn, session: WriteSession) -> HouseholdOut:
    """Rename a household."""
    row = await session.get(Household, household.id)
    if row is not None:
        row.name = body.name
        await session.flush()
    return HouseholdOut.model_validate(row or household, from_attributes=True)


@router.delete("/households/{household_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household(household: MemberHousehold, session: WriteSession) -> Response:
    """Delete a household and all of its data."""
    await service.delete_household(session, household.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/households/{household_id}/members")
async def list_members(household: MemberHousehold, session: ReadSession) -> list[MemberOut]:
    """List members."""
    pairs = await service.members(session, household.id)
    return [MemberOut(user_id=u.id, display_name=u.display_name, joined_at=m.joined_at) for u, m in pairs]


@router.delete("/households/{household_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(household: MemberHousehold, user_id: uuid.UUID, session: WriteSession) -> Response:
    """Remove a member; removing the last member deletes the household."""
    await service.remove_member(session, household.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/households/{household_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    household: MemberHousehold, auth: CurrentAuth, session: WriteSession, request: Request
) -> InviteOut:
    """Mint a single-use invite link."""
    invite = await service.create_invite(session, household.id, auth.user.id)
    base = str(request.app.state.settings.public_url).rstrip("/")
    return InviteOut(code=invite.code, url=f"{base}/invite/{invite.code}", expires_at=invite.expires_at)


@router.post("/invites/{code}/accept")
async def accept_invite(code: str, auth: CurrentAuth, session: WriteSession) -> HouseholdOut:
    """Join the household behind an invite code."""
    household = await service.accept_invite(session, code, auth.user.id)
    return HouseholdOut.model_validate(household, from_attributes=True)
