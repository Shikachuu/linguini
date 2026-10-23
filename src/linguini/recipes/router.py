"""Recipe endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from linguini.auth.sessions import CurrentAuth
from linguini.db import ReadSession, WriteSession
from linguini.households.router import MemberHousehold
from linguini.inventory import service as inventory
from linguini.models import EventCause, Recipe, RecipeSource
from linguini.recipes import service
from linguini.recipes.service import MAX_SERVINGS, Ingredient, RecipeData

router = APIRouter(prefix="/api/households/{household_id}", tags=["recipes"])


class RecipeOut(BaseModel):
    """A stored recipe."""

    id: uuid.UUID
    title: str
    servings: int
    ingredients: list[Ingredient]
    steps: list[str]
    allergens: list[str]
    source: RecipeSource
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, recipe: Recipe) -> RecipeOut:
        """Convert a row.

        Returns:
            The API shape.
        """
        return cls.model_validate(recipe, from_attributes=True)


class CookIn(BaseModel):
    """How many portions were made; omit for the recipe's own servings."""

    servings: int | None = Field(default=None, ge=1, le=MAX_SERVINGS)


class CookLine(BaseModel):
    """What cooking did to one ingredient."""

    name: str
    ok: bool
    message: str
    event_id: uuid.UUID | None


class CookResult(BaseModel):
    """What cooking consumed."""

    recipe: RecipeOut
    results: list[CookLine]


@router.get("/recipes")
async def list_recipes(
    household: MemberHousehold, session: ReadSession, q: Annotated[str | None, Query(max_length=80)] = None
) -> list[RecipeOut]:
    """List or search recipes by title or ingredient."""
    return [RecipeOut.from_row(r) for r in await service.list_recipes(session, household.id, q)]


@router.post("/recipes", status_code=status.HTTP_201_CREATED)
async def create_recipe(household: MemberHousehold, body: RecipeData, session: WriteSession) -> RecipeOut:
    """Save a recipe."""
    return RecipeOut.from_row(await service.create_recipe(session, household.id, body, source=RecipeSource.MANUAL))


@router.get("/recipes/{recipe_id}")
async def get_recipe(household: MemberHousehold, recipe_id: uuid.UUID, session: ReadSession) -> RecipeOut:
    """Return one recipe."""
    return RecipeOut.from_row(await service.get_recipe(session, household.id, recipe_id))


@router.put("/recipes/{recipe_id}")
async def replace_recipe(
    household: MemberHousehold, recipe_id: uuid.UUID, body: RecipeData, session: WriteSession
) -> RecipeOut:
    """Replace a recipe's content."""
    return RecipeOut.from_row(await service.replace_recipe(session, household.id, recipe_id, body))


@router.delete("/recipes/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(household: MemberHousehold, recipe_id: uuid.UUID, session: WriteSession) -> Response:
    """Delete a recipe."""
    await service.delete_recipe(session, household.id, recipe_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/recipes/{recipe_id}/cook")
async def cook_recipe(
    household: MemberHousehold,
    recipe_id: uuid.UUID,
    auth: CurrentAuth,
    session: WriteSession,
    body: CookIn | None = None,
) -> CookResult:
    """Consume the recipe's ingredients from the inventory; an empty body means the recipe's servings."""
    actor = inventory.Actor(EventCause.COOK, auth.user.id)
    servings = body.servings if body is not None else None
    recipe, batch = await service.cook_recipe(session, household.id, recipe_id, actor, servings)
    results = [
        CookLine(name=r.name, ok=r.ok, message=r.message, event_id=r.event.id if r.event else None)
        for r in batch.results
    ]
    return CookResult(recipe=RecipeOut.from_row(recipe), results=results)
