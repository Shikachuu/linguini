import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from linguini.db import Database, run_migrations
from linguini.inventory import service
from linguini.inventory.units import Unit
from linguini.models import EventCause, Household, Run, Thread, User

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    path = tmp_path / "t.db"
    run_migrations(path)
    database = Database(path)
    yield database
    await database.dispose()


@pytest.fixture
async def home(db: Database) -> uuid.UUID:
    async with db.write_lock, db.write_session() as session:
        household = Household(name="H")
        session.add(household)
        await session.commit()
        return household.id


async def new_runs(db: Database, home: uuid.UUID, count: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with db.write_lock, db.write_session() as session:
        user = User(display_name="u")
        session.add(user)
        await session.flush()
        thread = Thread(household_id=home, created_by=user.id)
        session.add(thread)
        await session.flush()
        runs = [Run(thread_id=thread.id, user_id=user.id) for _ in range(count)]
        session.add_all(runs)
        await session.commit()
        return thread.id, [r.id for r in runs]


def chat(run_id: uuid.UUID, thread_id: uuid.UUID) -> service.Actor:
    return service.Actor(EventCause.CHAT, thread_id=thread_id, run_id=run_id)


async def test_consume_clamps_and_reports_shortfall(db: Database, home: uuid.UUID) -> None:
    async with db.write_lock, db.write_session() as session:
        await service.add_items(
            session, home, [service.ItemChange("rizs", 300, Unit.G)], service.Actor(EventCause.MANUAL)
        )
        batch = await service.consume_items(
            session,
            home,
            [service.ItemChange("rizs", 0.5, Unit.KG), service.ItemChange("bab", 1, Unit.KG)],
            service.Actor(EventCause.COOK),
        )
        await session.commit()
    rice, beans = batch.results
    assert rice.ok and rice.shortfall_base == 200 and "short by 200 g" in rice.message
    assert rice.item is not None and rice.item.quantity_base == 0
    assert not beans.ok and beans.shortfall_base == 1000


async def test_undo_last_turn_reverts_only_the_latest_run(db: Database, home: uuid.UUID) -> None:
    thread, (run1, run2) = await new_runs(db, home, 2)
    async with db.write_lock, db.write_session() as session:
        await service.add_items(session, home, [service.ItemChange("rizs", 1, Unit.KG)], chat(run1, thread))
        await service.consume_items(
            session,
            home,
            [service.ItemChange("rizs", 200, Unit.G), service.ItemChange("tej", 1, Unit.L)],
            chat(run2, thread),
        )
        await session.commit()
    async with db.write_lock, db.write_session() as session:
        undone = await service.undo_last_turn(session, home, thread, service.Actor(EventCause.UNDO))
        await session.commit()
    assert len(undone) == 1
    async with db.read_session() as session:
        rice = await service.get_by_name(session, home, "rizs")
    assert rice is not None and rice.quantity_base == 1000
    async with db.write_lock, db.write_session() as session:
        again = await service.undo_last_turn(session, home, thread, service.Actor(EventCause.UNDO))
        await session.commit()
    assert len(again) == 1
    async with db.read_session() as session:
        rice = await service.get_by_name(session, home, "rizs")
    assert rice is not None and rice.quantity_base == 0


async def test_kifli_order_is_imported_once(db: Database, home: uuid.UUID) -> None:
    change = [service.ItemChange("csirkemell", 500, Unit.G, kifli_product_id="123")]
    async with db.write_lock, db.write_session() as session:
        first = await service.add_items(
            session, home, change, service.Actor(EventCause.KIFLI_ORDER), kifli_order_id="o1"
        )
        second = await service.add_items(
            session, home, change, service.Actor(EventCause.KIFLI_ORDER), kifli_order_id="o1"
        )
        await session.commit()
    assert first.results[0].ok
    assert second.skipped_duplicate_order and second.results == []
    async with db.read_session() as session:
        item = await service.get_by_name(session, home, "Csirkemell")
    assert item is not None and item.quantity_base == 500 and item.kifli_product_id == "123"


async def test_consume_with_dimension_mismatch_changes_nothing(db: Database, home: uuid.UUID) -> None:
    manual = service.Actor(EventCause.MANUAL)
    async with db.write_lock, db.write_session() as session:
        await service.add_items(session, home, [service.ItemChange("tej", 1, Unit.L)], manual)
        batch = await service.consume_items(session, home, [service.ItemChange("tej", 200, Unit.G)], manual)
        await session.commit()
    assert not batch.results[0].ok and "tracked in l" in batch.results[0].message
    async with db.read_session() as session:
        item = await service.get_by_name(session, home, "tej")
        events = await service.list_events(session, home)
    assert item is not None and item.quantity_base == 1000
    assert len(events) == 1


async def test_consume_converts_within_dimension_and_can_empty(db: Database, home: uuid.UUID) -> None:
    manual = service.Actor(EventCause.MANUAL)
    async with db.write_lock, db.write_session() as session:
        await service.add_items(session, home, [service.ItemChange("tej", 1, Unit.L)], manual)
        first = await service.consume_items(session, home, [service.ItemChange("tej", 2, Unit.DL)], manual)
        second = await service.consume_items(session, home, [service.ItemChange("tej", 8, Unit.DL)], manual)
        await session.commit()
    assert first.results[0].event is not None and first.results[0].event.quantity_after == 800
    assert second.results[0].shortfall_base == 0
    assert second.results[0].event is not None and second.results[0].event.quantity_after == 0


async def test_undo_last_turn_skips_hand_undone_events_and_other_threads(db: Database, home: uuid.UUID) -> None:
    thread_a, (run_a,) = await new_runs(db, home, 1)
    thread_b, (run_b,) = await new_runs(db, home, 1)
    async with db.write_lock, db.write_session() as session:
        batch = await service.add_items(
            session,
            home,
            [service.ItemChange("rizs", 1, Unit.KG), service.ItemChange("tej", 1, Unit.L)],
            chat(run_a, thread_a),
        )
        await service.add_items(session, home, [service.ItemChange("bab", 1, Unit.KG)], chat(run_b, thread_b))
        await service.undo_event(session, home, batch.events[0].id, service.Actor(EventCause.UNDO))
        await session.commit()
    async with db.write_lock, db.write_session() as session:
        undone = await service.undo_last_turn(session, home, thread_a, service.Actor(EventCause.UNDO))
        await session.commit()
    assert [u.item_id for u in undone] == [batch.events[1].item_id]
    async with db.read_session() as session:
        beans = await service.get_by_name(session, home, "bab")
    assert beans is not None and beans.quantity_base == 1000


async def test_failed_order_import_can_be_retried(db: Database, home: uuid.UUID) -> None:
    actor = service.Actor(EventCause.KIFLI_ORDER)
    async with db.write_lock, db.write_session() as session:
        await service.add_items(session, home, [service.ItemChange("tej", 1, Unit.L)], service.Actor(EventCause.MANUAL))
        failed = await service.add_items(
            session, home, [service.ItemChange("tej", 1, Unit.KG)], actor, kifli_order_id="o9"
        )
        retried = await service.add_items(
            session, home, [service.ItemChange("tej", 1, Unit.L)], actor, kifli_order_id="o9"
        )
        await session.commit()
    assert not failed.results[0].ok and not failed.skipped_duplicate_order
    assert retried.results[0].ok and not retried.skipped_duplicate_order
