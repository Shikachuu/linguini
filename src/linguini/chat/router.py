"""Chat threads and the streaming chat endpoint."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from linguini.auth.sessions import CurrentAuth
from linguini.chat import history
from linguini.chat.agent import RUN_TIMEOUT, USAGE_LIMITS
from linguini.chat.deps import AgentDeps
from linguini.db import Database, ReadSession, WriteSession, get_database, utcnow
from linguini.households import service as households
from linguini.households.router import MemberHousehold
from linguini.inventory import service as inventory
from linguini.models import InventoryEvent, Run, RunStatus, Thread

router = APIRouter(prefix="/api/households/{household_id}", tags=["chat"])
log = logging.getLogger(__name__)

UNTITLED = "New chat"
STALE_LOCK_AFTER = timedelta(seconds=RUN_TIMEOUT + 60)


class ThreadIn(BaseModel):
    """Create or rename a thread."""

    title: str | None = Field(default=None, max_length=80)


class ThreadOut(BaseModel):
    """A chat thread."""

    id: uuid.UUID
    title: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ThreadDetail(ThreadOut):
    """A thread with its messages in Vercel AI SDK UIMessage form."""

    messages: list[dict[str, Any]]


def _thread_out(thread: Thread) -> ThreadOut:
    return ThreadOut.model_validate(thread, from_attributes=True)


async def _get_thread(session: AsyncSession, household_id: uuid.UUID, thread_id: uuid.UUID) -> Thread:
    thread = await session.get(Thread, thread_id)
    if thread is None or thread.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return thread


@router.get("/threads")
async def list_threads(household: MemberHousehold, session: ReadSession) -> list[ThreadOut]:
    """Threads of the household, most recently active first."""
    rows = await session.execute(
        select(Thread).where(Thread.household_id == household.id).order_by(col(Thread.updated_at).desc())
    )
    return [_thread_out(t) for t in rows.scalars()]


@router.post("/threads", status_code=status.HTTP_201_CREATED)
async def create_thread(
    household: MemberHousehold, body: ThreadIn, auth: CurrentAuth, session: WriteSession
) -> ThreadOut:
    """Start a thread."""
    thread = Thread(household_id=household.id, created_by=auth.user.id, title=body.title or UNTITLED)
    session.add(thread)
    await session.flush()
    return _thread_out(thread)


@router.get("/threads/{thread_id}")
async def get_thread(household: MemberHousehold, thread_id: uuid.UUID, session: ReadSession) -> ThreadDetail:
    """A thread with its full message history for the UI, including prompts of failed runs."""
    thread = await _get_thread(session, household.id, thread_id)
    runs = await history.stored_runs(session, thread.id, include_failed=True)
    ui = VercelAIAdapter.dump_messages(history.thread_messages(runs))
    return ThreadDetail(
        **_thread_out(thread).model_dump(), messages=[m.model_dump(mode="json", by_alias=True) for m in ui]
    )


@router.patch("/threads/{thread_id}")
async def rename_thread(
    household: MemberHousehold, thread_id: uuid.UUID, body: ThreadIn, session: WriteSession
) -> ThreadOut:
    """Rename a thread."""
    thread = await _get_thread(session, household.id, thread_id)
    if body.title:
        thread.title = body.title
    await session.flush()
    return _thread_out(thread)


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(household: MemberHousehold, thread_id: uuid.UUID, session: WriteSession) -> Response:
    """Delete a thread and its runs; inventory events keep their thread id but lose the run link."""
    thread = await _get_thread(session, household.id, thread_id)
    run_ids = (await session.execute(select(Run.id).where(Run.thread_id == thread.id))).scalars().all()
    if run_ids:
        await session.execute(update(InventoryEvent).where(col(InventoryEvent.run_id).in_(run_ids)).values(run_id=None))
        for run in (await session.execute(select(Run).where(col(Run.id).in_(run_ids)))).scalars():
            await session.delete(run)
    await session.delete(thread)
    await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ThreadLocks:
    """One run at a time per thread, with recovery from a lock a crashed stream never released."""

    def __init__(self) -> None:
        """Start with no held threads."""
        self._held: dict[uuid.UUID, datetime] = {}

    def acquire(self, thread_id: uuid.UUID) -> bool:
        """Take the thread if free or stale.

        Returns:
            False when another run owns the thread.
        """
        since = self._held.get(thread_id)
        if since is not None and utcnow() - since < STALE_LOCK_AFTER:
            return False
        if since is not None:
            log.warning("thread %s lock was stale; taking it over", thread_id)
        self._held[thread_id] = utcnow()
        return True

    def release(self, thread_id: uuid.UUID) -> None:
        """Free the thread."""
        self._held.pop(thread_id, None)

    def is_held(self, thread_id: uuid.UUID) -> bool:
        """Whether a run owns the thread.

        Returns:
            True while held.
        """
        return thread_id in self._held


def _prompt_text(message: UIMessage) -> str:
    return "\n".join(p.text for p in message.parts if isinstance(p, TextUIPart)).strip()


def _newest_user_message(messages: list[UIMessage]) -> UIMessage:
    for message in reversed(messages):
        if message.role == "user":
            return message
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No user message in request")


@router.post("/threads/{thread_id}/chat", response_class=StreamingResponse)
async def chat(
    household: MemberHousehold,
    thread_id: uuid.UUID,
    auth: CurrentAuth,
    request: Request,
    db: Annotated[Database, Depends(get_database)],
) -> StreamingResponse:
    """Send a message and stream the reply as a Vercel AI SDK data stream.

    Only the newest user message from the request body is used; the conversation history
    comes from the server.

    Raises:
        HTTPException: 409 when the thread already has a run in progress.
    """
    settings = request.app.state.settings
    agent: Agent[AgentDeps, str] = request.app.state.agent
    run_input = VercelAIAdapter.build_run_input(await request.body())
    if not isinstance(run_input, SubmitMessage):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only submit-message is supported")
    prompt = _newest_user_message(run_input.messages)
    run_input.messages = [prompt]

    locks: ThreadLocks = request.app.state.thread_locks
    if not locks.acquire(thread_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This thread is already answering")
    try:
        async with db.read_session() as session:
            thread = await _get_thread(session, household.id, thread_id)
        await history.summarize_if_needed(db, thread_id, request.app.state.summarizer, settings.history_token_budget)
        async with db.read_session() as session:
            model_history = await history.model_history(session, thread)
            members = [u.display_name for u, _ in await households.members(session, household.id)]
            items = await inventory.list_items(session, household.id)
        run = Run(thread_id=thread_id, user_id=auth.user.id)
        async with db.write_lock, db.write_session() as session:
            session.add(run)
            await session.commit()
        now = utcnow()
        deps = AgentDeps(
            db=db,
            household_id=household.id,
            household_name=household.name,
            member_names=members,
            user_id=auth.user.id,
            user_name=auth.user.display_name,
            thread_id=thread_id,
            run_id=run.id,
            now=now,
            locale=settings.locale,
            inventory_snapshot=history.inventory_snapshot(items, now),
        )
        adapter = VercelAIAdapter(agent, run_input, accept=request.headers.get("accept"))
        bookkeeper = _RunBookkeeper(db, locks, run.id, thread_id, _prompt_text(prompt), thread.title == UNTITLED)
        stream = adapter.run_stream(
            message_history=model_history,
            deps=deps,
            usage_limits=USAGE_LIMITS,
            timeout=RUN_TIMEOUT,
            on_complete=bookkeeper.on_complete,
            on_cancel=bookkeeper.on_cancel,
        )
        response = adapter.streaming_response(bookkeeper.wrap(stream))
    except BaseException:
        locks.release(thread_id)
        raise
    return response


class _RunBookkeeper:
    """Records how a run ended, whatever happens to the HTTP stream, then frees the thread."""

    def __init__(
        self, db: Database, locks: ThreadLocks, run_id: uuid.UUID, thread_id: uuid.UUID, prompt: str, untitled: bool
    ) -> None:
        self.db = db
        self.locks = locks
        self.run_id = run_id
        self.thread_id = thread_id
        self.prompt = prompt
        self.untitled = untitled
        self.status = RunStatus.FAILED
        self.new_messages: list[ModelMessage] = []

    async def on_complete(self, result: AgentRunResult[Any]) -> None:
        self.status = RunStatus.COMPLETED
        self.new_messages = list(result.new_messages())

    async def on_cancel(self, exc: RunCancelled) -> None:
        self.status = RunStatus.CANCELLED
        self.new_messages = list(exc.new_messages())

    async def wrap(self, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        try:
            async for chunk in stream:
                yield chunk
        finally:
            task = self.db.write_later(self._store)
            task.add_done_callback(lambda _: self.locks.release(self.thread_id))
            await asyncio.shield(task)

    async def _store(self, session: AsyncSession) -> None:
        run = await session.get(Run, self.run_id)
        if run is None:
            return
        finished = utcnow()
        prompt_message = ModelRequest(parts=[UserPromptPart(self.prompt)])
        run.status = self.status
        run.messages = history.dump_messages([prompt_message, *self.new_messages])
        run.finished_at = finished
        thread = await session.get(Thread, self.thread_id)
        if thread is not None:
            thread.updated_at = finished
            if self.untitled and self.prompt:
                thread.title = history.title_from(self.prompt)
