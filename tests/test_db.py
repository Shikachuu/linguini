from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from linguini.db import Database, run_migrations
from linguini.models import Household

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    path = tmp_path / "t.db"
    run_migrations(path)
    database = Database(path)
    yield database
    await database.dispose()


async def test_write_then_read_restores_utc(db: Database) -> None:
    async with db.write_lock, db.write_session() as session:
        session.add(Household(name="Home", created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)))
        await session.commit()
    async with db.read_session() as session:
        row = (await session.execute(select(Household))).scalar_one()
    assert row.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert row.created_at.tzinfo is UTC


async def test_naive_datetime_is_rejected(db: Database) -> None:
    async with db.write_lock, db.write_session() as session:
        session.add(Household(name="Home", created_at=datetime.fromisoformat("2026-01-02T00:00:00")))
        with pytest.raises(StatementError, match="naive datetime"):
            await session.commit()


async def test_write_begins_immediate_and_read_begins_deferred(db: Database) -> None:
    writes: list[str] = []
    reads: list[str] = []
    event.listen(db.write_engine.sync_engine, "before_cursor_execute", lambda *a: writes.append(a[2]))
    event.listen(db.read_engine.sync_engine, "before_cursor_execute", lambda *a: reads.append(a[2]))
    async with db.write_lock, db.write_session() as session:
        session.add(Household(name="Home"))
        await session.commit()
    async with db.read_session() as session:
        await session.execute(select(Household))
    assert writes[0] == "BEGIN IMMEDIATE"
    assert reads[0] == "BEGIN"


async def test_write_later_runs_after_lock_is_released(db: Database) -> None:
    async def work(session: AsyncSession) -> None:
        await session.flush()
        session.add(Household(name="Later"))

    async with db.write_lock, db.write_session() as session:
        db.write_later(work)
        session.add(Household(name="Now"))
        await session.commit()
    await db.drain()
    async with db.read_session() as session:
        names = sorted((await session.execute(select(Household.name))).scalars())
    assert names == ["Later", "Now"]
