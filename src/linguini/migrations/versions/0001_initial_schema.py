"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-22 15:12:50.252185
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

import linguini.db

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


FTS_UP = (
    """
    CREATE VIRTUAL TABLE inventory_items_fts USING fts5(
        name, content='inventory_items', content_rowid='rowid',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TRIGGER inventory_items_ai AFTER INSERT ON inventory_items BEGIN
        INSERT INTO inventory_items_fts(rowid, name) VALUES (new.rowid, new.name);
    END
    """,
    """
    CREATE TRIGGER inventory_items_ad AFTER DELETE ON inventory_items BEGIN
        INSERT INTO inventory_items_fts(inventory_items_fts, rowid, name) VALUES ('delete', old.rowid, old.name);
    END
    """,
    """
    CREATE TRIGGER inventory_items_au AFTER UPDATE OF name ON inventory_items BEGIN
        INSERT INTO inventory_items_fts(inventory_items_fts, rowid, name) VALUES ('delete', old.rowid, old.name);
        INSERT INTO inventory_items_fts(rowid, name) VALUES (new.rowid, new.name);
    END
    """,
)
FTS_DOWN = (
    "DROP TRIGGER IF EXISTS inventory_items_au",
    "DROP TRIGGER IF EXISTS inventory_items_ad",
    "DROP TRIGGER IF EXISTS inventory_items_ai",
    "DROP TABLE IF EXISTS inventory_items_fts",
)


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_households")),
    )
    op.create_table(
        "kifli_clients",
        sa.Column("issuer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("registration", sa.JSON(), nullable=True),
        sa.Column("redirect_uris", sa.JSON(), nullable=True),
        sa.Column("paste_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("issuer", name=op.f("pk_kifli_clients")),
    )
    op.create_table(
        "oauth_states",
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("nonce", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("code_verifier", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("binding_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("intent", sa.Enum("LOGIN", "LINK", "KIFLI", name="oauthintent"), nullable=False),
        sa.Column("invite_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("household_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("return_to", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("expires_at", linguini.db.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("state", name=op.f("pk_oauth_states")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("deleted_at", linguini.db.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Enum("APPLE", "GOOGLE", name="provider"), nullable=False),
        sa.Column("subject", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("is_private_email", sa.Boolean(), nullable=False),
        sa.Column("apple_refresh_token_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("last_login_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_identities_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identities")),
        sa.UniqueConstraint("provider", "subject", name=op.f("uq_identities_provider_subject")),
    )
    with op.batch_alter_table("identities", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_identities_user_id"), ["user_id"], unique=False)

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name_normalized", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("dimension", sa.Enum("MASS", "VOLUME", "COUNT", name="dimension"), nullable=False),
        sa.Column("quantity_base", sa.Float(), nullable=False),
        sa.Column("display_unit", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kifli_product_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("last_purchased_at", linguini.db.UTCDateTime(), nullable=True),
        sa.Column("expires_at", linguini.db.UTCDateTime(), nullable=True),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name=op.f("fk_inventory_items_household_id_households")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_items")),
        sa.UniqueConstraint(
            "household_id", "name_normalized", name=op.f("uq_inventory_items_household_id_name_normalized")
        ),
    )
    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_inventory_items_household_id"), ["household_id"], unique=False)

    op.create_table(
        "invites",
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("expires_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_at", linguini.db.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_invites_created_by_users")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], name=op.f("fk_invites_household_id_households")),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], name=op.f("fk_invites_used_by_users")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_invites")),
    )
    with op.batch_alter_table("invites", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_invites_household_id"), ["household_id"], unique=False)

    op.create_table(
        "kifli_connections",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("mcp_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("issuer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("client_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("access_token_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("refresh_token_enc", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("expires_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("broken", sa.Boolean(), nullable=False),
        sa.Column("connected_by", sa.Uuid(), nullable=False),
        sa.Column("connected_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["connected_by"], ["users.id"], name=op.f("fk_kifli_connections_connected_by_users")),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name=op.f("fk_kifli_connections_household_id_households")
        ),
        sa.PrimaryKeyConstraint("household_id", name=op.f("pk_kifli_connections")),
    )
    op.create_table(
        "kifli_imported_orders",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("imported_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name=op.f("fk_kifli_imported_orders_household_id_households")
        ),
        sa.PrimaryKeyConstraint("household_id", "order_id", name=op.f("pk_kifli_imported_orders")),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("joined_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name=op.f("fk_memberships_household_id_households")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users")),
        sa.PrimaryKeyConstraint("user_id", "household_id", name=op.f("pk_memberships")),
    )
    op.create_table(
        "recipes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("servings", sa.Integer(), nullable=False),
        sa.Column("ingredients", sa.JSON(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("allergens", sa.JSON(), nullable=True),
        sa.Column("source", sa.Enum("CHAT", "MANUAL", name="recipesource"), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], name=op.f("fk_recipes_household_id_households")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipes")),
    )
    with op.batch_alter_table("recipes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_recipes_household_id"), ["household_id"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_kind", sa.Enum("WEB", "MOBILE", name="clientkind"), nullable=False),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("expires_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("user_agent", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_through_run_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_threads_created_by_users")),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], name=op.f("fk_threads_household_id_households")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threads")),
    )
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_threads_household_id"), ["household_id"], unique=False)

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Enum("RUNNING", "COMPLETED", "CANCELLED", "FAILED", name="runstatus"), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.Column("finished_at", linguini.db.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name=op.f("fk_runs_thread_id_threads")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_runs_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_thread_id"), ["thread_id"], unique=False)

    op.create_table(
        "inventory_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("delta_base", sa.Float(), nullable=False),
        sa.Column("quantity_before", sa.Float(), nullable=False),
        sa.Column("quantity_after", sa.Float(), nullable=False),
        sa.Column("cause", sa.Enum("MANUAL", "CHAT", "COOK", "KIFLI_ORDER", "UNDO", name="eventcause"), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("tool_call_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("undone_by_event_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", linguini.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_inventory_events_actor_user_id_users")),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name=op.f("fk_inventory_events_household_id_households")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["inventory_items.id"], name=op.f("fk_inventory_events_item_id_inventory_items")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_inventory_events_run_id_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_events")),
    )
    with op.batch_alter_table("inventory_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_inventory_events_household_id"), ["household_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_inventory_events_item_id"), ["item_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_inventory_events_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_inventory_events_thread_id"), ["thread_id"], unique=False)

    for statement in FTS_UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in FTS_DOWN:
        op.execute(statement)
    with op.batch_alter_table("inventory_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inventory_events_thread_id"))
        batch_op.drop_index(batch_op.f("ix_inventory_events_run_id"))
        batch_op.drop_index(batch_op.f("ix_inventory_events_item_id"))
        batch_op.drop_index(batch_op.f("ix_inventory_events_household_id"))

    op.drop_table("inventory_events")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_thread_id"))

    op.drop_table("runs")
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_threads_household_id"))

    op.drop_table("threads")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_user_id"))

    op.drop_table("sessions")
    with op.batch_alter_table("recipes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recipes_household_id"))

    op.drop_table("recipes")
    op.drop_table("memberships")
    op.drop_table("kifli_imported_orders")
    op.drop_table("kifli_connections")
    with op.batch_alter_table("invites", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_invites_household_id"))

    op.drop_table("invites")
    with op.batch_alter_table("inventory_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inventory_items_household_id"))

    op.drop_table("inventory_items")
    with op.batch_alter_table("identities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_identities_user_id"))

    op.drop_table("identities")
    op.drop_table("users")
    op.drop_table("oauth_states")
    op.drop_table("kifli_clients")
    op.drop_table("households")
