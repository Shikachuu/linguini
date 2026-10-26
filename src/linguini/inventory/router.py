"""Inventory endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator

from linguini.auth.sessions import CurrentAuth
from linguini.db import ReadSession, UTCInput, WriteSession
from linguini.households.router import MemberHousehold
from linguini.inventory import service
from linguini.inventory.units import Unit, dimension_of, from_base, parse_unit
from linguini.models import Dimension, EventCause, InventoryEvent, InventoryItem

router = APIRouter(prefix="/api/households/{household_id}", tags=["inventory"])


class ItemIn(BaseModel):
    """Add a quantity to an item, creating it if needed."""

    name: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0)
    unit: str
    purchased_at: UTCInput | None = None
    expires_at: UTCInput | None = None
    kifli_product_id: str | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        return parse_unit(value).value


class ItemPatch(BaseModel):
    """Set an item's absolute quantity or metadata."""

    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    expires_at: UTCInput | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str | None) -> str | None:
        return parse_unit(value).value if value is not None else None


class ItemOut(BaseModel):
    """An inventory item in its display unit."""

    id: uuid.UUID
    name: str
    quantity: float
    unit: str
    dimension: Dimension
    kifli_product_id: str | None
    last_purchased_at: datetime | None
    expires_at: datetime | None
    notes: str | None
    updated_at: datetime

    @classmethod
    def from_item(cls, item: InventoryItem) -> ItemOut:
        """Convert a row.

        Returns:
            The API shape.
        """
        return cls(
            id=item.id,
            name=item.name,
            quantity=from_base(item.quantity_base, Unit(item.display_unit)),
            unit=item.display_unit,
            dimension=item.dimension,
            kifli_product_id=item.kifli_product_id,
            last_purchased_at=item.last_purchased_at,
            expires_at=item.expires_at,
            notes=item.notes,
            updated_at=item.updated_at,
        )


class EventOut(BaseModel):
    """An audit event."""

    id: uuid.UUID
    item_id: uuid.UUID
    delta_base: float
    quantity_before: float
    quantity_after: float
    dimension: Dimension
    unit: str
    cause: EventCause
    thread_id: uuid.UUID | None
    run_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    undone_by_event_id: uuid.UUID | None
    created_at: datetime


def _out(events: list[InventoryEvent]) -> list[EventOut]:
    return [EventOut.model_validate(e, from_attributes=True) for e in events]


@router.get("/items")
async def list_items(
    household: MemberHousehold, session: ReadSession, q: Annotated[str | None, Query(max_length=80)] = None
) -> list[ItemOut]:
    """List or search items."""
    items = (
        await service.search_items(session, household.id, q) if q else await service.list_items(session, household.id)
    )
    return [ItemOut.from_item(i) for i in items]


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def add_item(household: MemberHousehold, body: ItemIn, auth: CurrentAuth, session: WriteSession) -> ItemOut:
    """Add a quantity, creating the item if it does not exist.

    Raises:
        HTTPException: 409 when the unit's dimension conflicts with the stored item.
    """
    change = service.ItemChange(
        body.name, body.quantity, Unit(body.unit), body.purchased_at, body.expires_at, body.kifli_product_id, body.notes
    )
    batch = await service.add_items(session, household.id, [change], service.Actor(EventCause.MANUAL, auth.user.id))
    result = batch.results[0]
    if not result.ok or result.item is None:
        raise HTTPException(status.HTTP_409_CONFLICT, result.message)
    return ItemOut.from_item(result.item)


@router.patch("/items/{item_id}")
async def patch_item(
    household: MemberHousehold, item_id: uuid.UUID, body: ItemPatch, auth: CurrentAuth, session: WriteSession
) -> ItemOut:
    """Set the absolute quantity, unit, expiry, or notes of an item.

    Send ``null`` for ``expires_at`` or ``notes`` to clear them.

    Raises:
        HTTPException: 422 when the unit changes dimension without a quantity.
    """
    item = await service.get_item(session, household.id, item_id)
    if body.quantity is not None or body.unit is not None:
        unit = Unit(body.unit) if body.unit else Unit(item.display_unit)
        if body.quantity is None and dimension_of(unit) != item.dimension:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Changing the dimension needs a quantity")
        quantity = body.quantity if body.quantity is not None else from_base(item.quantity_base, unit)
        change = service.ItemChange(item.name, quantity, unit)
        result = await service.set_item(session, household.id, change, service.Actor(EventCause.MANUAL, auth.user.id))
        if result.item is not None:
            item = result.item
    if "expires_at" in body.model_fields_set:
        item.expires_at = body.expires_at
    if "notes" in body.model_fields_set:
        item.notes = body.notes
    await session.flush()
    return ItemOut.from_item(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(household: MemberHousehold, item_id: uuid.UUID, session: WriteSession) -> Response:
    """Delete an item and its history."""
    await service.remove_item(session, household.id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events")
async def list_events(
    household: MemberHousehold, session: ReadSession, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[EventOut]:
    """Newest inventory events first."""
    return _out(await service.list_events(session, household.id, limit))


@router.post("/events/{event_id}/undo")
async def undo_event(
    household: MemberHousehold, event_id: uuid.UUID, auth: CurrentAuth, session: WriteSession
) -> EventOut:
    """Revert one event."""
    undo = await service.undo_event(session, household.id, event_id, service.Actor(EventCause.UNDO, auth.user.id))
    return EventOut.model_validate(undo, from_attributes=True)


@router.post("/events/undo-last-turn")
async def undo_last_turn(
    household: MemberHousehold, thread_id: uuid.UUID, auth: CurrentAuth, session: WriteSession
) -> list[EventOut]:
    """Revert every change made by the latest agent run in a thread."""
    actor = service.Actor(EventCause.UNDO, auth.user.id, thread_id=thread_id)
    return _out(await service.undo_last_turn(session, household.id, thread_id, actor))
