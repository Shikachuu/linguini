"""Persisting runs, rebuilding model history, and summarizing long threads."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from pydantic_ai import Agent, ModelMessage, ModelMessagesTypeAdapter, ModelSettings, UsageLimits
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
    repair_messages,
)
from pydantic_core import to_json, to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from linguini.chat.prompts import SUMMARY_INPUT, SummaryInput
from linguini.db import Database
from linguini.inventory.units import Unit, format_quantity
from linguini.models import InventoryItem, Run, RunStatus, Thread

KEEP_RECENT_RUNS = 6
SNAPSHOT_LINES = 20
EXPIRY_WINDOW = timedelta(days=3)
OLD_PURCHASE = timedelta(days=7)
SUMMARY_PREFIX = "Summary of the earlier part of this conversation:\n"
SUMMARY_TIMEOUT = 60.0
SUMMARY_LIMITS = UsageLimits(request_limit=1)
TEXT_CAP = 2000
log = logging.getLogger(__name__)


def dump_messages(messages: Sequence[ModelMessage]) -> list[Any]:
    """Serialize messages for the JSON column.

    Returns:
        JSON-compatible data.
    """
    return to_jsonable_python(messages)


def load_messages(data: list[Any] | None) -> list[ModelMessage]:
    """Deserialize a stored run's messages.

    Returns:
        The messages, or an empty list when the run stored none.
    """
    return [] if not data else list(ModelMessagesTypeAdapter.validate_python(data))


async def stored_runs(
    session: AsyncSession, thread_id: uuid.UUID, after: uuid.UUID | None = None, *, include_failed: bool = False
) -> list[Run]:
    """Finished runs of a thread with messages, oldest first.

    Failed runs hold only the user's prompt; the UI shows them, the model does not see them.

    Returns:
        Runs after ``after`` (exclusive) when given, else all.
    """
    statuses = [RunStatus.COMPLETED, RunStatus.CANCELLED] + ([RunStatus.FAILED] if include_failed else [])
    query = select(Run).where(Run.thread_id == thread_id, col(Run.status).in_(statuses), col(Run.messages).is_not(None))
    if after is not None:
        query = query.where(col(Run.id) > after)
    rows = await session.execute(query.order_by(col(Run.created_at), col(Run.id)))
    return list(rows.scalars())


def thread_messages(runs: Sequence[Run]) -> list[ModelMessage]:
    """Concatenate run messages into one repaired history.

    Returns:
        The messages, with dangling tool calls repaired.
    """
    messages: list[ModelMessage] = []
    for run in runs:
        messages.extend(load_messages(run.messages))
    return repair_messages(messages)


async def model_history(session: AsyncSession, thread: Thread) -> list[ModelMessage]:
    """What the model sees: the stored summary, then the runs after it.

    Returns:
        The history to pass as ``message_history``.
    """
    runs = await stored_runs(session, thread.id, thread.summary_through_run_id)
    history = thread_messages(runs)
    if thread.summary:
        history.insert(0, ModelRequest(parts=[UserPromptPart(SUMMARY_PREFIX + thread.summary)]))
    return history


def estimate_tokens(messages: Sequence[ModelMessage]) -> int:
    """Rough token count without a tokenizer.

    Returns:
        Serialized length divided by four.
    """
    return len(to_json(messages)) // 4


def render_for_summary(messages: Sequence[ModelMessage]) -> str:
    """Flatten messages into plain text for the summarizer.

    Returns:
        One line per part.
    """
    lines: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    lines.append(f"User: {part.content[:TEXT_CAP]}")
                elif isinstance(part, ToolReturnPart):
                    lines.append(f"Tool {part.tool_name} returned: {str(part.content)[:300]}")
        elif isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, TextPart):
                    lines.append(f"Assistant: {part.content[:TEXT_CAP]}")
                elif isinstance(part, ToolCallPart):
                    lines.append(f"Assistant called {part.tool_name}({part.args_as_json_str()[:300]})")
    return "\n".join(lines)


def summary_prompt(previous: str | None, conversation: str) -> str:
    """The summarizer's user prompt for ``conversation``, merging an earlier summary when there is one.

    Returns:
        The rendered prompt.
    """
    return SUMMARY_INPUT.render(SummaryInput(previous=previous or "", conversation=conversation))


async def summarize_if_needed(
    db: Database,
    thread_id: uuid.UUID,
    summarizer: Agent[None, str],
    budget: int,
    model_settings: ModelSettings | None = None,
) -> bool:
    """Fold older runs into the thread summary when the history exceeds ``budget`` tokens.

    A failing or slow summarizer is logged and skipped so the chat still answers.

    Returns:
        True when a new summary was stored.
    """
    folded = await _runs_to_fold(db, thread_id, budget)
    if folded is None:
        return False
    previous, runs = folded
    try:
        async with asyncio.timeout(SUMMARY_TIMEOUT):
            summary = await _fold(summarizer, previous, runs, model_settings)
    except Exception:
        log.exception("summarizing thread %s failed; continuing without a new summary", thread_id)
        return False
    await _store_summary(db, thread_id, summary, runs[-1].id)
    return True


async def _runs_to_fold(db: Database, thread_id: uuid.UUID, budget: int) -> tuple[str | None, list[Run]] | None:
    async with db.read_session() as session:
        thread = await session.get(Thread, thread_id)
        if thread is None:
            return None
        history = await model_history(session, thread)
        if estimate_tokens(history) <= budget:
            return None
        runs = await stored_runs(session, thread.id, thread.summary_through_run_id)
        previous = thread.summary
    if len(runs) <= KEEP_RECENT_RUNS:
        return None
    return previous, runs[:-KEEP_RECENT_RUNS]


async def _fold(
    summarizer: Agent[None, str], previous: str | None, runs: Sequence[Run], model_settings: ModelSettings | None
) -> str:
    prompt = summary_prompt(previous, render_for_summary(thread_messages(runs)))
    result = await summarizer.run(prompt, usage_limits=SUMMARY_LIMITS, model_settings=model_settings)
    return result.output


async def _store_summary(db: Database, thread_id: uuid.UUID, summary: str, through_run_id: uuid.UUID) -> None:
    async with db.write_lock, db.write_session() as session:
        row = await session.get(Thread, thread_id)
        if row is not None:
            row.summary = summary
            row.summary_through_run_id = through_run_id
            await session.commit()


def inventory_snapshot(items: Sequence[InventoryItem], now: datetime) -> str:
    """Items that expire soon or were bought a while ago, for the instructions.

    Returns:
        Up to ``SNAPSHOT_LINES`` lines, or an empty string.
    """
    lines: list[str] = []
    for item in items:
        if item.quantity_base <= 0:
            continue
        flags: list[str] = []
        if item.expires_at is not None:
            days = (item.expires_at - now).days
            if days < 0:
                flags.append(f"expired {-days} days ago")
            elif item.expires_at - now <= EXPIRY_WINDOW:
                flags.append(f"expires in {days} days")
        elif item.last_purchased_at is not None and now - item.last_purchased_at >= OLD_PURCHASE:
            flags.append(f"bought {(now - item.last_purchased_at).days} days ago")
        if flags:
            lines.append(
                f"- {item.name}: {format_quantity(item.quantity_base, Unit(item.display_unit))} ({', '.join(flags)})"
            )
    return "\n".join(lines[:SNAPSHOT_LINES])


def title_from(text: str) -> str:
    """Derive a thread title from the first prompt.

    Returns:
        The first line, trimmed to 60 characters.
    """
    first = text.strip().splitlines()[0] if text.strip() else "New chat"
    return first[:60].rstrip() or "New chat"
