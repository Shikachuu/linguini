"""Inventory tools exposed to the agent."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from linguini.chat.deps import AgentDeps
from linguini.db import UTCInput
from linguini.inventory import service
from linguini.inventory.units import Unit, format_quantity, parse_unit
from linguini.models import EventCause, InventoryItem, Recipe, RecipeSource
from linguini.recipes import service as recipes
from linguini.recipes.service import MAX_SERVINGS, RecipeData

inventory_toolset: FunctionToolset[AgentDeps] = FunctionToolset(id="inventory")


class ItemAmount(BaseModel):
    """A named quantity, e.g. 500 g of chicken breast."""

    name: str = Field(
        min_length=1, max_length=80, description="Item name as the household calls it, e.g. 'csirkemell' or 'rice'"
    )
    quantity: float = Field(gt=0, description="Positive amount in `unit`")
    unit: str = Field(description="g, dkg, kg, ml, dl, l, tsp, tbsp, cup or pcs (db)")

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        return parse_unit(value).value

    @field_validator("name")
    @classmethod
    def _one_line(cls, value: str) -> str:
        return " ".join(value.split())


class PurchasedItem(ItemAmount):
    """An item being added to the pantry."""

    purchased_at: UTCInput | None = Field(default=None, description="When it was bought; defaults to now")
    expires_at: UTCInput | None = Field(default=None, description="Best-before date if known")
    kifli_product_id: str | None = Field(
        default=None, max_length=64, description="Kifli product id when imported from an order"
    )


def _actor(ctx: RunContext[AgentDeps], cause: EventCause = EventCause.CHAT) -> service.Actor:
    d = ctx.deps
    return service.Actor(cause, d.user_id, d.thread_id, d.run_id, ctx.tool_call_id)


def _item_view(item: InventoryItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "quantity": format_quantity(item.quantity_base, Unit(item.display_unit)),
        "last_purchased_at": item.last_purchased_at.date().isoformat() if item.last_purchased_at else None,
        "expires_at": item.expires_at.date().isoformat() if item.expires_at else None,
        "notes": item.notes,
    }


def _batch_view(batch: service.BatchResult) -> dict[str, Any]:
    return {
        "results": [
            {"ok": r.ok, "message": r.message, "event_id": str(r.event.id) if r.event else None} for r in batch.results
        ],
        "skipped_duplicate_order": batch.skipped_duplicate_order,
    }


@inventory_toolset.tool
async def list_items(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """List every item in the household's inventory with its current quantity.

    Returns:
        One entry per item.
    """
    async with ctx.deps.db.read_session() as session:
        return [_item_view(i) for i in await service.list_items(session, ctx.deps.household_id)]


@inventory_toolset.tool
async def search_items(ctx: RunContext[AgentDeps], query: Annotated[str, Field(max_length=80)]) -> list[dict[str, Any]]:
    """Search the inventory by name; accents and case do not matter and prefixes match.

    Args:
        query: One or more words of the item name.

    Returns:
        Matching items, best match first.
    """
    async with ctx.deps.db.read_session() as session:
        return [_item_view(i) for i in await service.search_items(session, ctx.deps.household_id, query)]


@inventory_toolset.tool
async def add_items(
    ctx: RunContext[AgentDeps],
    items: list[PurchasedItem],
    kifli_order_id: Annotated[str, Field(max_length=64)] | None = None,
) -> dict[str, Any]:
    """Add quantities to the inventory, creating items that do not exist yet.

    Use this for purchases, deliveries, and corrections upwards. When importing a Kifli order,
    pass its ``kifli_order_id`` so the same order is never imported twice.

    Args:
        items: What was added, with positive quantities.
        kifli_order_id: The Kifli order id when the items come from an order.

    Returns:
        Per-item outcome messages and event ids for undo.
    """
    changes = [
        service.ItemChange(i.name, i.quantity, Unit(i.unit), i.purchased_at, i.expires_at, i.kifli_product_id)
        for i in items
    ]
    cause = EventCause.KIFLI_ORDER if kifli_order_id else EventCause.CHAT
    d = ctx.deps
    async with d.db.write_lock, d.db.write_session() as session:
        batch = await service.add_items(
            session, d.household_id, changes, _actor(ctx, cause), kifli_order_id=kifli_order_id
        )
        await session.commit()
    return _batch_view(batch)


@inventory_toolset.tool
async def consume_items(ctx: RunContext[AgentDeps], items: list[ItemAmount]) -> dict[str, Any]:
    """Subtract quantities after cooking, eating, or throwing something away.

    Quantities never go below zero; a shortfall is reported in the message.

    Args:
        items: What was used, with positive quantities.

    Returns:
        Per-item outcome messages and event ids for undo.
    """
    changes = [service.ItemChange(i.name, i.quantity, Unit(i.unit)) for i in items]
    d = ctx.deps
    async with d.db.write_lock, d.db.write_session() as session:
        batch = await service.consume_items(session, d.household_id, changes, _actor(ctx))
        await session.commit()
    return _batch_view(batch)


@inventory_toolset.tool
async def set_item(
    ctx: RunContext[AgentDeps],
    item: ItemAmount,
    expires_at: UTCInput | None = None,
    notes: Annotated[str, Field(max_length=500)] | None = None,
) -> dict[str, Any]:
    """Set an item's absolute quantity, optionally changing its unit, expiry, or notes.

    Args:
        item: The item and the exact amount it now has (0 is allowed to mark it as used up).
        expires_at: New best-before date, if the user gave one.
        notes: Free-text note such as 'opened on Monday'.

    Returns:
        The outcome message and the event id for undo.
    """
    change = service.ItemChange(item.name, item.quantity, Unit(item.unit), expires_at=expires_at, notes=notes)
    d = ctx.deps
    async with d.db.write_lock, d.db.write_session() as session:
        result = await service.set_item(session, d.household_id, change, _actor(ctx))
        await session.commit()
    return {"ok": result.ok, "message": result.message, "event_id": str(result.event.id) if result.event else None}


@inventory_toolset.tool
async def remove_item(
    ctx: RunContext[AgentDeps], name: Annotated[str, Field(max_length=80)], user_confirmed: bool
) -> str:
    """Permanently delete an item and its history; this cannot be undone.

    Only call this after the user explicitly confirmed the deletion in this conversation.
    Otherwise use set_item with quantity 0.

    Args:
        name: The item name.
        user_confirmed: True only if the user explicitly confirmed deleting this item.

    Returns:
        A confirmation message.

    Raises:
        ModelRetry: when the user has not confirmed or no item has that name.
    """
    if not user_confirmed:
        raise ModelRetry("Ask the user to confirm the permanent deletion first, or use set_item with quantity 0.")
    d = ctx.deps
    async with d.db.write_lock, d.db.write_session() as session:
        item = await service.get_by_name(session, d.household_id, name)
        if item is None:
            raise ModelRetry(f"No item named {name!r}; use search_items to find the right name.")
        await service.remove_item(session, d.household_id, item.id)
        await session.commit()
    return f"Removed {item.name}."


@inventory_toolset.tool
async def undo(
    ctx: RunContext[AgentDeps], event_id: Annotated[str, Field(max_length=64)] | None = None
) -> dict[str, Any]:
    """Undo inventory changes: one event by id, or every change made by the previous assistant turn.

    Without an id this works once per turn and never touches changes made in the current turn;
    to revert something you just did, pass its event id.

    Args:
        event_id: An event id returned by an earlier tool call; omit to undo the previous turn.

    Returns:
        The compensating events.

    Raises:
        ModelRetry: when the event cannot be undone.
    """
    d = ctx.deps
    actor = _actor(ctx, EventCause.UNDO)
    if event_id:
        try:
            target = uuid.UUID(event_id)
        except ValueError as exc:
            raise ModelRetry("Cannot undo: event_id must be an id returned by an earlier tool call.") from exc
    elif d.undid_previous_turn:
        raise ModelRetry("The previous turn was already undone in this turn; pass an event id to undo more.")
    else:
        target = None
    try:
        async with d.db.write_lock, d.db.write_session() as session:
            if target is not None:
                events = [await service.undo_event(session, d.household_id, target, actor)]
            else:
                events = await service.undo_last_turn(
                    session, d.household_id, d.thread_id, actor, exclude_run_id=d.run_id
                )
            await session.commit()
    except HTTPException as exc:
        raise ModelRetry(f"Cannot undo: {exc.detail}") from exc
    if target is None:
        d.undid_previous_turn = True
    return {"undone": len(events), "events": [{"id": str(e.id), "item_id": str(e.item_id)} for e in events]}


recipe_toolset: FunctionToolset[AgentDeps] = FunctionToolset(id="recipes")


def _recipe_view(recipe: Recipe, *, full: bool) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": str(recipe.id),
        "title": recipe.title,
        "servings": recipe.servings,
        "allergens": recipe.allergens,
    }
    if full:
        view["ingredients"] = recipe.ingredients
        view["steps"] = recipe.steps
    return view


@recipe_toolset.tool
async def list_recipes(
    ctx: RunContext[AgentDeps], query: Annotated[str, Field(max_length=80)] | None = None
) -> list[dict[str, Any]]:
    """List the household's saved recipes, optionally filtered by title or ingredient.

    Args:
        query: A word from the title or an ingredient name; omit to list everything.

    Returns:
        Recipes with id, title, servings and allergens; use get_recipe for the full content.
    """
    async with ctx.deps.db.read_session() as session:
        rows = await recipes.list_recipes(session, ctx.deps.household_id, query)
    return [_recipe_view(r, full=False) for r in rows]


@recipe_toolset.tool
async def get_recipe(ctx: RunContext[AgentDeps], recipe_id: Annotated[str, Field(max_length=64)]) -> dict[str, Any]:
    """Return a saved recipe with its ingredients and steps.

    Args:
        recipe_id: The id from list_recipes or save_recipe.

    Returns:
        The full recipe.

    Raises:
        ModelRetry: when the id is unknown.
    """
    async with ctx.deps.db.read_session() as session:
        try:
            recipe = await recipes.get_recipe(session, ctx.deps.household_id, _recipe_uuid(recipe_id))
        except HTTPException as exc:
            raise ModelRetry(str(exc.detail)) from exc
    return _recipe_view(recipe, full=True)


@recipe_toolset.tool
async def save_recipe(ctx: RunContext[AgentDeps], recipe: RecipeData) -> dict[str, Any]:
    """Save a recipe the user wants to keep, including one you invented in this conversation.

    Always include every allergen the dish contains. Quantities are per the given servings.

    Args:
        recipe: Title, servings, ingredients with quantities and units, steps, and allergens.

    Returns:
        The saved recipe's id and title.
    """
    d = ctx.deps
    async with d.db.write_lock, d.db.write_session() as session:
        row = await recipes.create_recipe(
            session, d.household_id, recipe, source=RecipeSource.CHAT, thread_id=d.thread_id
        )
        await session.commit()
    return _recipe_view(row, full=False)


@recipe_toolset.tool
async def cook_recipe(
    ctx: RunContext[AgentDeps], recipe_id: Annotated[str, Field(max_length=64)], servings: int | None = None
) -> dict[str, Any]:
    """Record that a saved recipe was cooked: its required ingredients are consumed from the inventory.

    Use this when the user says they made a dish that is saved; for unsaved dishes use consume_items.

    Args:
        recipe_id: The id from list_recipes.
        servings: Portions actually made, 1 to 100; defaults to the recipe's servings.

    Returns:
        Per-ingredient outcomes with shortfalls and event ids for undo.

    Raises:
        ModelRetry: when the id is unknown or servings is out of range.
    """
    d = ctx.deps
    if servings is not None and not 1 <= servings <= MAX_SERVINGS:
        raise ModelRetry(f"servings must be between 1 and {MAX_SERVINGS}")
    try:
        async with d.db.write_lock, d.db.write_session() as session:
            row, batch = await recipes.cook_recipe(
                session, d.household_id, _recipe_uuid(recipe_id), _actor(ctx, EventCause.COOK), servings
            )
            await session.commit()
    except HTTPException as exc:
        raise ModelRetry(str(exc.detail)) from exc
    return {"recipe": _recipe_view(row, full=False), **_batch_view(batch)}


def _recipe_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ModelRetry("recipe_id must be an id returned by list_recipes or save_recipe.") from exc
