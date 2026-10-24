import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai import Agent, ModelSettings
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from linguini.chat import history
from linguini.db import Database, run_migrations
from linguini.inventory.units import Unit
from linguini.models import Dimension, Household, InventoryItem, Run, RunStatus, Thread, User

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    path = tmp_path / "t.db"
    run_migrations(path)
    database = Database(path)
    yield database
    await database.dispose()


def exchange(i: int) -> list:
    return [ModelRequest(parts=[UserPromptPart(f"question {i}")]), ModelResponse(parts=[TextPart(f"answer {i}")])]


def completed_run(thread_id: uuid.UUID, user_id: uuid.UUID, i: int) -> Run:
    return Run(
        thread_id=thread_id, user_id=user_id, status=RunStatus.COMPLETED, messages=history.dump_messages(exchange(i))
    )


async def seed_thread(db: Database, runs: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with db.write_lock, db.write_session() as session:
        user = User(display_name="u")
        household = Household(name="H")
        session.add_all([user, household])
        await session.flush()
        thread = Thread(household_id=household.id, created_by=user.id)
        session.add(thread)
        await session.flush()
        rows = [
            Run(
                thread_id=thread.id,
                user_id=user.id,
                status=RunStatus.COMPLETED,
                messages=history.dump_messages(exchange(i)),
            )
            for i in range(runs)
        ]
        session.add_all(rows)
        await session.commit()
        return thread.id, [r.id for r in rows]


async def test_summarize_folds_old_runs_and_keeps_recent(db: Database) -> None:
    thread_id, run_ids = await seed_thread(db, 8)
    summarizer: Agent[None, str] = Agent(TestModel(custom_output_text="SUMMARY"))
    assert await history.summarize_if_needed(db, thread_id, summarizer, budget=1)
    async with db.read_session() as session:
        thread = await session.get(Thread, thread_id)
        assert thread is not None
        assert thread.summary == "SUMMARY" and thread.summary_through_run_id == run_ids[1]
        messages = await history.model_history(session, thread)
    assert "SUMMARY" in str(messages[0])
    assert len(messages) == 1 + 6 * 2
    assert "question 2" in str(messages[1]) and "question 1" not in str(messages)


async def test_summarize_skips_when_under_budget_or_too_short(db: Database) -> None:
    thread_id, _ = await seed_thread(db, 8)
    summarizer: Agent[None, str] = Agent(TestModel(custom_output_text="SUMMARY"))
    assert not await history.summarize_if_needed(db, thread_id, summarizer, budget=10_000_000)
    short_id, _ = await seed_thread(db, 3)
    assert not await history.summarize_if_needed(db, short_id, summarizer, budget=1)


async def test_summarize_merges_previous_summary(db: Database) -> None:
    thread_id, _ = await seed_thread(db, 8)
    seen: list[str] = []

    def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        assert isinstance(last, ModelRequest)
        prompt = last.parts[0]
        assert isinstance(prompt, UserPromptPart)
        seen.append(str(prompt.content))
        return ModelResponse(parts=[TextPart("NEW")])

    summarizer: Agent[None, str] = Agent(FunctionModel(capture))
    await history.summarize_if_needed(db, thread_id, summarizer, budget=1)
    async with db.write_lock, db.write_session() as session:
        thread = await session.get(Thread, thread_id)
        assert thread is not None
        session.add_all([completed_run(thread_id, thread.created_by, i) for i in range(8, 10)])
        await session.commit()
    await history.summarize_if_needed(db, thread_id, summarizer, budget=1)
    assert "Earlier summary:\nNEW" in seen[-1]
    assert "question 2" in seen[-1] and "question 9" not in seen[-1]


def test_inventory_snapshot_flags_only_relevant_items() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    hid = uuid.uuid7()

    def item(
        name: str, quantity: float, *, last_purchased_at: datetime | None = None, expires_at: datetime | None = None
    ) -> InventoryItem:
        return InventoryItem(
            household_id=hid,
            name=name,
            name_normalized=name,
            dimension=Dimension.MASS,
            display_unit=Unit.G.value,
            quantity_base=quantity,
            last_purchased_at=last_purchased_at,
            expires_at=expires_at,
        )

    items = [
        item("old meat", 500, last_purchased_at=now - timedelta(days=8)),
        item("fresh", 500, last_purchased_at=now - timedelta(days=1)),
        item("expiring", 100, expires_at=now + timedelta(days=2)),
        item("expired", 100, expires_at=now - timedelta(days=1)),
        item("empty", 0, expires_at=now - timedelta(days=1)),
    ]
    snapshot = history.inventory_snapshot(items, now)
    assert snapshot.splitlines() == [
        "- old meat: 500 g (bought 8 days ago)",
        "- expiring: 100 g (expires in 2 days)",
        "- expired: 100 g (expired 1 days ago)",
    ]


def test_title_and_token_estimate() -> None:
    assert history.title_from("  Mit főzzek ma este?\nrészletek") == "Mit főzzek ma este?"
    assert history.title_from("") == "New chat"
    assert history.estimate_tokens(exchange(1)) > 0


@pytest.mark.parametrize(("run_count", "expected"), [(6, False), (7, True)])
async def test_summarize_boundary_at_keep_recent_runs(db: Database, run_count: int, expected: bool) -> None:
    thread_id, run_ids = await seed_thread(db, run_count)
    summarizer: Agent[None, str] = Agent(TestModel(custom_output_text="S"))
    assert await history.summarize_if_needed(db, thread_id, summarizer, budget=1) is expected
    if expected:
        async with db.read_session() as session:
            thread = await session.get(Thread, thread_id)
            assert thread is not None and thread.summary_through_run_id == run_ids[0]


async def test_summarizer_failure_is_skipped(db: Database) -> None:
    thread_id, _ = await seed_thread(db, 8)

    def explode(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("no summary today")

    summarizer: Agent[None, str] = Agent(FunctionModel(explode))
    assert await history.summarize_if_needed(db, thread_id, summarizer, budget=1) is False
    async with db.read_session() as session:
        thread = await session.get(Thread, thread_id)
        assert thread is not None and thread.summary is None


def test_inventory_snapshot_caps_lines_and_prefers_expiry() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    hid = uuid.uuid7()
    old = now - timedelta(days=30)
    items = [
        InventoryItem(
            household_id=hid,
            name=f"item{i}",
            name_normalized=f"item{i}",
            dimension=Dimension.COUNT,
            display_unit="pcs",
            quantity_base=1,
            last_purchased_at=old,
            expires_at=now + timedelta(days=1) if i == 0 else None,
        )
        for i in range(25)
    ]
    lines = history.inventory_snapshot(items, now).splitlines()
    assert len(lines) == history.SNAPSHOT_LINES
    assert lines[0] == "- item0: 1 pcs (expires in 1 days)"


def test_title_is_trimmed_to_sixty_characters() -> None:
    assert len(history.title_from("x" * 100)) == 60


async def test_summarizer_gets_the_session_settings(db: Database) -> None:
    thread_id, _ = await seed_thread(db, 8)
    seen: list[object] = []

    def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.model_settings)
        return ModelResponse(parts=[TextPart("S")])

    settings = ModelSettings(extra_headers={"x-opencode-session": f"{thread_id}:summary"})
    assert await history.summarize_if_needed(db, thread_id, Agent(FunctionModel(capture)), 1, settings)
    assert seen == [settings]
