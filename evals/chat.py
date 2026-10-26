import tempfile
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, ModelMessage
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_evals import increment_eval_metric

from linguini.chat import history
from linguini.chat.agent import RUN_TIMEOUT, USAGE_LIMITS, build_agent, session_settings
from linguini.chat.deps import AgentDeps
from linguini.config import Settings
from linguini.db import Database, run_migrations, utcnow
from linguini.inventory import service as inventory
from linguini.inventory.units import parse_unit
from linguini.models import EventCause, Household, Membership, RecipeSource, Run, RunStatus, Thread, User
from linguini.recipes import service as recipes
from linguini.recipes.service import RecipeData


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class Stock(BaseModel):
    name: str
    quantity: float
    unit: str
    bought_days_ago: int = 0
    expires_in_days: int | None = None
    notes: str | None = None


class ChatInputs(BaseModel):
    messages: list[str]
    history: list[Turn] = []
    inventory: list[Stock] = []
    recipes: list[RecipeData] = []
    household_name: str = "Kovács"
    members: list[str] = ["Anna", "Béla"]
    user_name: str = "Anna"
    locale: str = "hu-HU"


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]


class StockLevel(BaseModel):
    name: str
    quantity_base: float
    unit: str


class ChatOutcome(BaseModel):
    reply: str
    replies: list[str]
    tool_calls: list[ToolCall]
    inventory: list[StockLevel]


def chat_task(model: Model, settings: Settings) -> Callable[[ChatInputs], Awaitable[ChatOutcome]]:
    agent = build_agent(model)

    async def run(inputs: ChatInputs) -> ChatOutcome:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.db"
            run_migrations(path)
            db = Database(path)
            try:
                return await _converse(agent, db, settings, inputs)
            finally:
                await db.dispose()

    return run


async def _converse(agent: Agent[AgentDeps, str], db: Database, settings: Settings, inputs: ChatInputs) -> ChatOutcome:
    household_id, user_id, thread_id = await _seed(db, inputs)
    messages = _history(inputs.history)
    calls: list[ToolCall] = []
    replies: list[str] = []
    for text in inputs.messages:
        async with db.read_session() as session:
            items = await inventory.list_items(session, household_id)
        run_id = await _new_run(db, thread_id, user_id)
        now = utcnow()
        deps = AgentDeps(
            db=db,
            household_id=household_id,
            household_name=inputs.household_name,
            member_names=inputs.members,
            user_id=user_id,
            user_name=inputs.user_name,
            thread_id=thread_id,
            run_id=run_id,
            now=now,
            locale=inputs.locale,
            inventory_snapshot=history.inventory_snapshot(items, now),
        )
        result = await agent.run(
            text,
            deps=deps,
            message_history=messages,
            usage_limits=USAGE_LIMITS,
            timeout=RUN_TIMEOUT,
            model_settings=session_settings(settings, str(thread_id)),
        )
        calls.extend(_tool_calls(result.new_messages()))
        messages = result.all_messages()
        replies.append(result.output)
        usage = result.usage
        increment_eval_metric("requests", usage.requests)
        increment_eval_metric("input_tokens", usage.input_tokens)
        increment_eval_metric("output_tokens", usage.output_tokens)
    async with db.read_session() as session:
        items = await inventory.list_items(session, household_id)
    stock = [StockLevel(name=i.name, quantity_base=i.quantity_base, unit=i.display_unit) for i in items]
    return ChatOutcome(reply=replies[-1] if replies else "", replies=replies, tool_calls=calls, inventory=stock)


async def _seed(db: Database, inputs: ChatInputs) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    now = utcnow()
    async with db.write_lock, db.write_session() as session:
        user = User(display_name=inputs.user_name)
        household = Household(name=inputs.household_name)
        session.add_all([user, household])
        await session.flush()
        thread = Thread(household_id=household.id, created_by=user.id)
        session.add_all([Membership(user_id=user.id, household_id=household.id), thread])
        changes = [
            inventory.ItemChange(
                s.name,
                s.quantity,
                parse_unit(s.unit),
                purchased_at=now - timedelta(days=s.bought_days_ago),
                expires_at=None if s.expires_in_days is None else now + timedelta(days=s.expires_in_days),
                notes=s.notes,
            )
            for s in inputs.inventory
        ]
        seeded = await inventory.add_items(session, household.id, changes, inventory.Actor(EventCause.MANUAL, user.id))
        if rejected := [r.message for r in seeded.results if not r.ok]:
            raise ValueError(f"case inventory rejected: {rejected}")
        for recipe in inputs.recipes:
            await recipes.create_recipe(session, household.id, recipe, source=RecipeSource.MANUAL)
        await session.commit()
        return household.id, user.id, thread.id


async def _new_run(db: Database, thread_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    async with db.write_lock, db.write_session() as session:
        run = Run(thread_id=thread_id, user_id=user_id, status=RunStatus.COMPLETED)
        session.add(run)
        await session.commit()
        return run.id


def _history(turns: list[Turn]) -> list[ModelMessage]:
    return [
        ModelRequest(parts=[UserPromptPart(t.text)]) if t.role == "user" else ModelResponse(parts=[TextPart(t.text)])
        for t in turns
    ]


def _tool_calls(messages: list[ModelMessage]) -> list[ToolCall]:
    return [
        ToolCall(name=part.tool_name, args=part.args_as_dict())
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
