"""Inventory operations: upsert, consume, search, audit events, undo."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from linguini.db import utcnow
from linguini.inventory.units import Unit, dimension_of, format_quantity, normalize_name, to_base
from linguini.models import Dimension, EventCause, InventoryEvent, InventoryItem, KifliImportedOrder

_TOKEN = re.compile(r"[^\w]+")


@dataclass(slots=True)
class Actor:
    """Who or what caused a change, for the audit log."""

    cause: EventCause
    user_id: uuid.UUID | None = None
    thread_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    tool_call_id: str | None = None


@dataclass(slots=True)
class ItemChange:
    """One requested change to an item."""

    name: str
    quantity: float
    unit: Unit
    purchased_at: datetime | None = None
    expires_at: datetime | None = None
    kifli_product_id: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ChangeResult:
    """Outcome of one requested change."""

    name: str
    ok: bool
    message: str
    item: InventoryItem | None = None
    event: InventoryEvent | None = None
    shortfall_base: float = 0


@dataclass(slots=True)
class BatchResult:
    """Outcome of a batch of changes."""

    results: list[ChangeResult] = field(default_factory=list)
    skipped_duplicate_order: bool = False

    @property
    def events(self) -> list[InventoryEvent]:
        """Events written by this batch.

        Returns:
            The events in request order.
        """
        return [r.event for r in self.results if r.event is not None]


async def list_items(session: AsyncSession, household_id: uuid.UUID) -> list[InventoryItem]:
    """All items of a household, by name.

    Returns:
        The items.
    """
    rows = await session.execute(
        select(InventoryItem).where(InventoryItem.household_id == household_id).order_by(col(InventoryItem.name))
    )
    return list(rows.scalars())


async def search_items(session: AsyncSession, household_id: uuid.UUID, query: str) -> list[InventoryItem]:
    """Full-text search with diacritics folding; falls back to a substring match.

    Returns:
        Matching items, best first.
    """
    cleaned = normalize_name(query)
    tokens = [t for t in _TOKEN.split(cleaned) if t]
    if not tokens:
        return await list_items(session, household_id)
    terms = " ".join(f'"{t}"*' for t in tokens)
    fts = text(
        "SELECT i.id FROM inventory_items i JOIN inventory_items_fts f ON f.rowid = i.rowid "
        "WHERE i.household_id = :hid AND inventory_items_fts MATCH :q ORDER BY bm25(inventory_items_fts) LIMIT 50"
    )
    ids = [uuid.UUID(row[0]) for row in (await session.execute(fts, {"hid": household_id.hex, "q": terms})).all()]
    if not ids:
        rows = await session.execute(
            select(InventoryItem)
            .where(
                InventoryItem.household_id == household_id,
                col(InventoryItem.name_normalized).contains(" ".join(tokens), autoescape=True),
            )
            .order_by(col(InventoryItem.name))
            .limit(50)
        )
        return list(rows.scalars())
    found = (await session.execute(select(InventoryItem).where(col(InventoryItem.id).in_(ids)))).scalars()
    by_id = {item.id: item for item in found}
    return [by_id[i] for i in ids if i in by_id]


async def get_by_name(session: AsyncSession, household_id: uuid.UUID, name: str) -> InventoryItem | None:
    """Exact lookup by normalized name.

    Returns:
        The item or None.
    """
    result = await session.execute(
        select(InventoryItem).where(
            InventoryItem.household_id == household_id, InventoryItem.name_normalized == normalize_name(name)
        )
    )
    return result.scalar_one_or_none()


async def get_item(session: AsyncSession, household_id: uuid.UUID, item_id: uuid.UUID) -> InventoryItem:
    """Load an item that belongs to the household.

    Returns:
        The item.

    Raises:
        HTTPException: 404 when missing.
    """
    item = await session.get(InventoryItem, item_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


async def add_items(
    session: AsyncSession,
    household_id: uuid.UUID,
    changes: list[ItemChange],
    actor: Actor,
    *,
    kifli_order_id: str | None = None,
) -> BatchResult:
    """Add quantities, creating items as needed; a Kifli order id is imported at most once.

    An order is only recorded as imported when at least one change succeeded, so a failed
    import can be retried.

    Returns:
        Per-change outcomes.
    """
    batch = BatchResult()
    if kifli_order_id is not None and not await _claim_order(session, household_id, kifli_order_id):
        batch.skipped_duplicate_order = True
        return batch
    for change in changes:
        batch.results.append(await _apply_delta(session, household_id, change, actor, sign=+1))
    if kifli_order_id is not None and not any(r.ok for r in batch.results):
        claimed = await session.get(KifliImportedOrder, (household_id, kifli_order_id))
        if claimed is not None:
            await session.delete(claimed)
    await session.flush()
    return batch


async def _claim_order(session: AsyncSession, household_id: uuid.UUID, order_id: str) -> bool:
    try:
        async with session.begin_nested():
            session.add(KifliImportedOrder(household_id=household_id, order_id=order_id))
            await session.flush()
    except IntegrityError:
        return False
    return True


async def consume_items(
    session: AsyncSession, household_id: uuid.UUID, changes: list[ItemChange], actor: Actor
) -> BatchResult:
    """Subtract quantities, clamping at zero and reporting shortfalls.

    Returns:
        Per-change outcomes.
    """
    batch = BatchResult()
    for change in changes:
        batch.results.append(await _apply_delta(session, household_id, change, actor, sign=-1))
    await session.flush()
    return batch


async def set_item(session: AsyncSession, household_id: uuid.UUID, change: ItemChange, actor: Actor) -> ChangeResult:
    """Set an absolute quantity, changing the unit and dimension if needed.

    A dimension change is logged as two events: one zeroing the old dimension and one setting the
    new one, so each stays undoable within its own dimension.

    Returns:
        The outcome.
    """
    dimension, base = to_base(change.quantity, change.unit)
    item = await get_by_name(session, household_id, change.name)
    if item is None:
        item = _new_item(household_id, change)
        session.add(item)
        await session.flush()
    if item.dimension != dimension and item.quantity_base:
        session.add(_event(item, item.quantity_base, 0.0, actor))
        item.quantity_base = 0.0
    before = item.quantity_base if item.dimension == dimension else 0.0
    item.dimension = dimension
    item.display_unit = change.unit.value
    item.quantity_base = base
    _touch(item, change)
    event = _event(item, before, base, actor)
    session.add(event)
    await session.flush()
    return ChangeResult(change.name, True, f"{item.name}: now {format_quantity(base, change.unit)}", item, event)


async def remove_item(session: AsyncSession, household_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """Delete an item and its audit trail; this is permanent and not undoable."""
    item = await get_item(session, household_id, item_id)
    for event in (await session.execute(select(InventoryEvent).where(InventoryEvent.item_id == item.id))).scalars():
        await session.delete(event)
    await session.delete(item)
    await session.flush()


async def list_events(session: AsyncSession, household_id: uuid.UUID, limit: int = 50) -> list[InventoryEvent]:
    """Newest events first.

    Returns:
        Up to ``limit`` events.
    """
    rows = await session.execute(
        select(InventoryEvent)
        .where(InventoryEvent.household_id == household_id)
        .order_by(col(InventoryEvent.created_at).desc(), col(InventoryEvent.id).desc())
        .limit(limit)
    )
    return list(rows.scalars())


async def undo_event(
    session: AsyncSession, household_id: uuid.UUID, event_id: uuid.UUID, actor: Actor
) -> InventoryEvent:
    """Revert one event by subtracting its delta; the quantity never goes below zero.

    Returns:
        The compensating event.

    Raises:
        HTTPException: 404 when unknown, 409 when already undone, itself an undo, or the item's
            dimension changed since.
    """
    event = await session.get(InventoryEvent, event_id)
    if event is None or event.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    if event.undone_by_event_id is not None or event.cause is EventCause.UNDO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Event cannot be undone")
    item = await session.get(InventoryItem, event.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item no longer exists")
    if item.dimension != event.dimension:
        raise HTTPException(status.HTTP_409_CONFLICT, "The item's unit changed since this event")
    before = item.quantity_base
    item.quantity_base = max(0.0, before - event.delta_base)
    item.updated_at = utcnow()
    undo = _event(
        item,
        before,
        item.quantity_base,
        Actor(EventCause.UNDO, actor.user_id, actor.thread_id, actor.run_id, actor.tool_call_id),
    )
    session.add(undo)
    await session.flush()
    event.undone_by_event_id = undo.id
    await session.flush()
    return undo


async def undo_last_turn(
    session: AsyncSession, household_id: uuid.UUID, thread_id: uuid.UUID, actor: Actor
) -> list[InventoryEvent]:
    """Revert every still-active event of the newest run in a thread that still has any.

    Calling it again walks back to the run before that, so repeated "undo" requests keep
    unwinding the thread's history.

    Returns:
        The compensating events, newest original first.
    """
    active = (
        InventoryEvent.household_id == household_id,
        InventoryEvent.cause != EventCause.UNDO,
        col(InventoryEvent.undone_by_event_id).is_(None),
    )
    latest = await session.execute(
        select(InventoryEvent.run_id)
        .where(*active, InventoryEvent.thread_id == thread_id, col(InventoryEvent.run_id).is_not(None))
        .order_by(col(InventoryEvent.created_at).desc(), col(InventoryEvent.id).desc())
        .limit(1)
    )
    run_id = latest.scalar_one_or_none()
    if run_id is None:
        return []
    events = await session.execute(
        select(InventoryEvent)
        .where(*active, InventoryEvent.run_id == run_id)
        .order_by(col(InventoryEvent.created_at).desc(), col(InventoryEvent.id).desc())
    )
    return [await undo_event(session, household_id, e.id, actor) for e in events.scalars().all()]


async def _apply_delta(
    session: AsyncSession, household_id: uuid.UUID, change: ItemChange, actor: Actor, *, sign: int
) -> ChangeResult:
    if change.quantity <= 0:
        return ChangeResult(change.name, False, f"{change.name}: quantity must be positive")
    dimension, delta = to_base(change.quantity, change.unit)
    item = await get_by_name(session, household_id, change.name)
    if item is None:
        if sign < 0:
            return ChangeResult(change.name, False, f"{change.name}: not in the inventory", shortfall_base=delta)
        item = _new_item(household_id, change)
        session.add(item)
        await session.flush()
    elif item.dimension != dimension:
        return ChangeResult(
            change.name,
            False,
            f"{item.name} is tracked in {item.display_unit} ({item.dimension.value}); "
            f"{change.unit.value} is {dimension.value}. Use set_item to change the unit.",
            item,
        )
    before = item.quantity_base
    after = before + delta if sign > 0 else max(0.0, before - delta)
    shortfall = max(0.0, delta - before) if sign < 0 else 0.0
    item.quantity_base = after
    if sign > 0:
        _touch(item, change, purchased=True)
    else:
        item.updated_at = utcnow()
    event = _event(item, before, after, actor)
    session.add(event)
    await session.flush()
    unit = Unit(item.display_unit)
    message = f"{item.name}: {format_quantity(before, unit)} -> {format_quantity(after, unit)}"
    if shortfall:
        message += f" (short by {format_quantity(shortfall, unit)})"
    return ChangeResult(change.name, True, message, item, event, shortfall)


def _new_item(household_id: uuid.UUID, change: ItemChange) -> InventoryItem:
    return InventoryItem(
        household_id=household_id,
        name=strip_name(change.name),
        name_normalized=normalize_name(change.name),
        dimension=dimension_of(change.unit),
        quantity_base=0,
        display_unit=change.unit.value,
        kifli_product_id=change.kifli_product_id,
        notes=change.notes,
    )


def _touch(item: InventoryItem, change: ItemChange, *, purchased: bool = False) -> None:
    now = utcnow()
    item.updated_at = now
    if purchased:
        item.last_purchased_at = change.purchased_at or now
    if change.expires_at is not None:
        item.expires_at = change.expires_at
    if change.kifli_product_id:
        item.kifli_product_id = change.kifli_product_id
    if change.notes is not None:
        item.notes = change.notes


def _event(item: InventoryItem, before: float, after: float, actor: Actor) -> InventoryEvent:
    return InventoryEvent(
        household_id=item.household_id,
        item_id=item.id,
        dimension=Dimension(item.dimension),
        unit=item.display_unit,
        delta_base=after - before,
        quantity_before=before,
        quantity_after=after,
        cause=actor.cause,
        thread_id=actor.thread_id,
        run_id=actor.run_id,
        tool_call_id=actor.tool_call_id,
        actor_user_id=actor.user_id,
    )


def strip_name(name: str) -> str:
    """Trim and collapse whitespace while keeping the user's spelling.

    Returns:
        The display name.
    """
    return " ".join(name.split())[:80]


__all__ = [
    "Actor",
    "BatchResult",
    "ChangeResult",
    "ItemChange",
    "add_items",
    "consume_items",
    "get_by_name",
    "get_item",
    "list_events",
    "list_items",
    "remove_item",
    "search_items",
    "set_item",
    "undo_event",
    "undo_last_turn",
]
