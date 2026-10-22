"""Alembic environment."""

from __future__ import annotations

import os

from alembic import context
from alembic.runtime.environment import NameFilterParentNames, NameFilterType
from sqlalchemy import Connection, create_engine

from linguini.models import metadata as target_metadata


def include_name(name: str | None, type_: NameFilterType, _parent_names: NameFilterParentNames) -> bool:
    """Keep the FTS5 virtual table and its shadow tables out of autogenerate.

    Returns:
        Whether Alembic should consider the object.
    """
    return not (type_ == "table" and name is not None and name.startswith("inventory_items_fts"))


def run_migrations(connection: Connection) -> None:
    """Configure the context on an open connection and run the migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    engine = create_engine(os.environ.get("LINGUINI_ALEMBIC_URL", "sqlite:///data/linguini.db"))
    with engine.connect() as conn:
        run_migrations(conn)
