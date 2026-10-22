"""SQLite engines, session dependencies, and startup migrations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, override

from alembic import command
from alembic.config import Config
from fastapi import Depends, Request
from sqlalchemy import Connection, DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
log = logging.getLogger(__name__)


class UTCDateTime(TypeDecorator[datetime]):
    """Store aware UTC datetimes as naive ISO strings and restore the UTC tzinfo on read."""

    impl = DateTime
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            msg = "naive datetime passed to UTCDateTime"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    """Return the current aware UTC time."""
    return datetime.now(tz=UTC)


def _apply_pragmas(dbapi_connection: DBAPIConnection, _record: object) -> None:
    cursor = dbapi_connection.cursor()
    for pragma in PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


def _begin_immediate(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def _begin_deferred(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")


class Database:
    """A read engine, a single-connection write engine, and their session factories."""

    def __init__(self, path: Path) -> None:
        """Create both engines for the SQLite file at ``path``."""
        url = f"sqlite+aiosqlite:///{path}"
        self.read_engine = create_async_engine(url, pool_size=4, max_overflow=4)
        self.write_engine = create_async_engine(url, poolclass=StaticPool)
        for engine, begin in ((self.read_engine, _begin_deferred), (self.write_engine, _begin_immediate)):
            event.listen(engine.sync_engine, "connect", _apply_pragmas)
            event.listen(engine.sync_engine, "connect", _disable_driver_transactions)
            event.listen(engine.sync_engine, "begin", begin)
        self.read_session = async_sessionmaker(self.read_engine, expire_on_commit=False)
        self.write_session = async_sessionmaker(self.write_engine, expire_on_commit=False)
        self.write_lock = asyncio.Lock()
        self._background: set[asyncio.Task[None]] = set()

    def write_later(self, work: Callable[[AsyncSession], Awaitable[None]]) -> None:
        """Run ``work`` in its own write transaction once the lock is free, without blocking the caller."""
        task = asyncio.create_task(self._run_write(work))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _run_write(self, work: Callable[[AsyncSession], Awaitable[None]]) -> None:
        try:
            async with self.write_lock, self.write_session() as session:
                await work(session)
                await session.commit()
        except Exception:
            log.exception("background write failed")

    async def drain(self) -> None:
        """Wait for queued background writes."""
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)

    async def dispose(self) -> None:
        """Finish background writes and close every pooled connection."""
        await self.drain()
        await self.read_engine.dispose()
        await self.write_engine.dispose()


def _disable_driver_transactions(dbapi_connection: DBAPIConnection, _record: object) -> None:
    dbapi_connection.isolation_level = None


def run_migrations(path: Path) -> None:
    """Upgrade the database file to the latest Alembic revision using a dedicated sync engine."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine: Engine = create_engine(f"sqlite:///{path}", isolation_level="AUTOCOMMIT")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def get_database(request: Request) -> Database:
    """Return the application's database holder."""
    return request.app.state.db


async def get_read_session(db: Annotated[Database, Depends(get_database)]) -> AsyncIterator[AsyncSession]:
    """Yield a session on the read pool."""
    async with db.read_session() as session:
        yield session


async def get_write_session(db: Annotated[Database, Depends(get_database)]) -> AsyncIterator[AsyncSession]:
    """Yield a session on the single write connection, committing on success."""
    async with db.write_lock, db.write_session() as session:
        yield session
        await session.commit()


ReadSession = Annotated[AsyncSession, Depends(get_read_session)]
WriteSession = Annotated[AsyncSession, Depends(get_write_session)]

__all__ = ["AsyncEngine", "Database", "ReadSession", "UTCDateTime", "WriteSession", "run_migrations", "utcnow"]
