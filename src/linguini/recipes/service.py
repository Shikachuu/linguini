"""Recipe storage and cooking, which drains the inventory."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from linguini.db import utcnow
from linguini.inventory import service as inventory
from linguini.inventory.units import Unit, normalize_name, parse_unit
from linguini.models import Recipe, RecipeSource


class Ingredient(BaseModel):
    """One line of a recipe."""

    name: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0)
    unit: str
    optional: bool = False

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        return parse_unit(value).value


MAX_SERVINGS = 100


class RecipeData(BaseModel):
    """Everything needed to create or replace a recipe."""

    title: str = Field(min_length=1, max_length=120)
    servings: int = Field(default=2, ge=1, le=MAX_SERVINGS)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=100)
    steps: list[str] = Field(default_factory=list, max_length=50)
    allergens: list[str] = Field(default_factory=list, max_length=30)

    def apply_to(self, recipe: Recipe) -> None:
        """Copy the normalized content onto a row."""
        recipe.title = self.title.strip()
        recipe.servings = self.servings
        recipe.ingredients = [i.model_dump() for i in self.ingredients]
        recipe.steps = [s.strip()[:1000] for s in self.steps if s.strip()]
        recipe.allergens = sorted({a.strip().lower()[:40] for a in self.allergens if a.strip()})


def ingredients_of(recipe: Recipe) -> list[Ingredient]:
    """Validated ingredient lines of a stored recipe.

    Returns:
        The ingredients; rows that no longer validate are skipped.
    """
    lines: list[Ingredient] = []
    for raw in recipe.ingredients:
        try:
            lines.append(Ingredient.model_validate(raw))
        except ValueError:
            continue
    return lines


async def list_recipes(session: AsyncSession, household_id: uuid.UUID, query: str | None = None) -> list[Recipe]:
    """Recipes of a household, optionally filtered by title or ingredient name.

    Returns:
        Matching recipes, newest first.
    """
    rows = await session.execute(
        select(Recipe).where(Recipe.household_id == household_id).order_by(col(Recipe.created_at).desc())
    )
    recipes = list(rows.scalars())
    needle = normalize_name(query or "")
    if not needle:
        return recipes
    return [r for r in recipes if needle in normalize_name(r.title) or _ingredient_match(r, needle)]


def _ingredient_match(recipe: Recipe, needle: str) -> bool:
    return any(needle in normalize_name(i.name) for i in ingredients_of(recipe))


async def get_recipe(session: AsyncSession, household_id: uuid.UUID, recipe_id: uuid.UUID) -> Recipe:
    """Load a recipe that belongs to the household.

    Returns:
        The recipe.

    Raises:
        HTTPException: 404 when missing.
    """
    recipe = await session.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return recipe


async def create_recipe(
    session: AsyncSession,
    household_id: uuid.UUID,
    data: RecipeData,
    *,
    source: RecipeSource,
    thread_id: uuid.UUID | None = None,
) -> Recipe:
    """Store a recipe.

    Returns:
        The new row.
    """
    recipe = Recipe(household_id=household_id, title=data.title, source=source, thread_id=thread_id)
    data.apply_to(recipe)
    session.add(recipe)
    await session.flush()
    return recipe


async def replace_recipe(
    session: AsyncSession, household_id: uuid.UUID, recipe_id: uuid.UUID, data: RecipeData
) -> Recipe:
    """Overwrite a recipe's content; ``source`` and ``thread_id`` stay as they were.

    Returns:
        The updated row.
    """
    recipe = await get_recipe(session, household_id, recipe_id)
    data.apply_to(recipe)
    recipe.updated_at = utcnow()
    await session.flush()
    return recipe


async def delete_recipe(session: AsyncSession, household_id: uuid.UUID, recipe_id: uuid.UUID) -> None:
    """Delete a recipe."""
    recipe = await get_recipe(session, household_id, recipe_id)
    await session.delete(recipe)
    await session.flush()


async def cook_recipe(
    session: AsyncSession,
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
    actor: inventory.Actor,
    servings: int | None = None,
) -> tuple[Recipe, inventory.BatchResult]:
    """Consume a recipe's required ingredients, scaled to ``servings``.

    Optional ingredients are skipped. Missing items and shortfalls are reported, not raised.

    Returns:
        The recipe and the per-ingredient outcomes.

    Raises:
        HTTPException: 422 when ``servings`` is out of range.
    """
    recipe = await get_recipe(session, household_id, recipe_id)
    portions = recipe.servings if servings is None else servings
    if not 1 <= portions <= MAX_SERVINGS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"servings must be between 1 and {MAX_SERVINGS}")
    scale = portions / recipe.servings
    changes = [
        inventory.ItemChange(i.name, round(i.quantity * scale, 3), Unit(i.unit))
        for i in ingredients_of(recipe)
        if not i.optional
    ]
    batch = await inventory.consume_items(session, household_id, changes, actor)
    return recipe, batch
