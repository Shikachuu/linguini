"""Every database table, declared with SQLModel."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, Enum, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from linguini.db import UTCDateTime, utcnow

metadata = SQLModel.metadata
metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _uuid() -> uuid.UUID:
    return uuid.uuid7()


def _enum[E: StrEnum](kind: type[E]) -> Enum:
    return Enum(kind, values_callable=lambda members: [m.value for m in members], native_enum=False, length=20)


class Provider(StrEnum):
    """Identity providers."""

    APPLE = "apple"
    GOOGLE = "google"


class ClientKind(StrEnum):
    """Which kind of client a session was minted for."""

    WEB = "web"
    MOBILE = "mobile"


class OAuthIntent(StrEnum):
    """Why an OAuth state row exists."""

    LOGIN = "login"
    LINK = "link"
    KIFLI = "kifli"


class Dimension(StrEnum):
    """Physical dimension of an inventory quantity."""

    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


class EventCause(StrEnum):
    """What produced an inventory change."""

    MANUAL = "manual"
    CHAT = "chat"
    COOK = "cook"
    KIFLI_ORDER = "kifli_order"
    UNDO = "undo"


class RecipeSource(StrEnum):
    """Where a recipe came from."""

    CHAT = "chat"
    MANUAL = "manual"


class RunStatus(StrEnum):
    """Lifecycle of an agent run."""

    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class User(SQLModel, table=True):
    """A person who can sign in."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    display_name: str
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    deleted_at: datetime | None = Field(default=None, sa_type=UTCDateTime)


class Identity(SQLModel, table=True):
    """One provider subject linked to a user."""

    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    provider: Provider = Field(sa_type=_enum(Provider))
    subject: str
    email: str | None = None
    email_verified: bool = False
    is_private_email: bool = False
    apple_refresh_token_enc: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    last_login_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Session(SQLModel, table=True):
    """An opaque login session; only the token hash is stored."""

    __tablename__ = "sessions"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    token_hash: str = Field(unique=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    client_kind: ClientKind = Field(sa_type=_enum(ClientKind))
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    last_seen_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    expires_at: datetime = Field(sa_type=UTCDateTime)
    user_agent: str | None = None


class OAuthState(SQLModel, table=True):
    """Pending authorization-code flow, shared by Apple, Google, and Kifli."""

    __tablename__ = "oauth_states"

    state: str = Field(primary_key=True)
    provider: str
    nonce: str | None = None
    code_verifier: str | None = None
    binding_hash: str | None = None
    intent: OAuthIntent = Field(sa_type=_enum(OAuthIntent))
    invite_code: str | None = None
    household_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    return_to: str | None = None
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    expires_at: datetime = Field(sa_type=UTCDateTime)


class Household(SQLModel, table=True):
    """A shared kitchen."""

    __tablename__ = "households"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Membership(SQLModel, table=True):
    """A user belongs to a household."""

    __tablename__ = "memberships"

    user_id: uuid.UUID = Field(foreign_key="users.id", primary_key=True)
    household_id: uuid.UUID = Field(foreign_key="households.id", primary_key=True)
    joined_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Invite(SQLModel, table=True):
    """Single-use invite code into a household."""

    __tablename__ = "invites"

    code: str = Field(primary_key=True)
    household_id: uuid.UUID = Field(foreign_key="households.id", index=True)
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    expires_at: datetime = Field(sa_type=UTCDateTime)
    used_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    used_at: datetime | None = Field(default=None, sa_type=UTCDateTime)


class InventoryItem(SQLModel, table=True):
    """One pantry item; quantity is kept in the dimension's base unit."""

    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("household_id", "name_normalized"),)

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    household_id: uuid.UUID = Field(foreign_key="households.id", index=True)
    name: str
    name_normalized: str
    dimension: Dimension = Field(sa_type=_enum(Dimension))
    quantity_base: float = 0
    display_unit: str
    kifli_product_id: str | None = None
    last_purchased_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    expires_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class InventoryEvent(SQLModel, table=True):
    """Audit row for every quantity change; the unit of undo."""

    __tablename__ = "inventory_events"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    household_id: uuid.UUID = Field(foreign_key="households.id", index=True)
    item_id: uuid.UUID = Field(foreign_key="inventory_items.id", index=True)
    dimension: Dimension = Field(sa_type=_enum(Dimension))
    unit: str
    delta_base: float
    quantity_before: float
    quantity_after: float
    cause: EventCause = Field(sa_type=_enum(EventCause))
    thread_id: uuid.UUID | None = Field(default=None, index=True)
    run_id: uuid.UUID | None = Field(default=None, foreign_key="runs.id", index=True)
    tool_call_id: str | None = None
    actor_user_id: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    undone_by_event_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Recipe(SQLModel, table=True):
    """A saved recipe with structured ingredients."""

    __tablename__ = "recipes"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    household_id: uuid.UUID = Field(foreign_key="households.id", index=True)
    title: str
    servings: int = 2
    ingredients: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    steps: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    allergens: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source: RecipeSource = Field(default=RecipeSource.CHAT, sa_type=_enum(RecipeSource))
    thread_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class KifliClient(SQLModel, table=True):
    """Dynamically registered OAuth client, one per authorization server."""

    __tablename__ = "kifli_clients"

    issuer: str = Field(primary_key=True)
    client_id: str
    registration: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    redirect_uris: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    paste_only: bool = False
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class KifliConnection(SQLModel, table=True):
    """A household's Kifli tokens, encrypted at rest."""

    __tablename__ = "kifli_connections"

    household_id: uuid.UUID = Field(foreign_key="households.id", primary_key=True)
    mcp_url: str
    issuer: str
    client_id: str
    access_token_enc: str
    refresh_token_enc: str | None = None
    expires_at: datetime = Field(sa_type=UTCDateTime)
    scope: str | None = None
    broken: bool = False
    connected_by: uuid.UUID = Field(foreign_key="users.id")
    connected_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class KifliImportedOrder(SQLModel, table=True):
    """Orders already imported into the inventory."""

    __tablename__ = "kifli_imported_orders"

    household_id: uuid.UUID = Field(foreign_key="households.id", primary_key=True)
    order_id: str = Field(primary_key=True)
    imported_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)


class Thread(SQLModel, table=True):
    """A chat thread shared by a household."""

    __tablename__ = "threads"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    household_id: uuid.UUID = Field(foreign_key="households.id", index=True)
    title: str = "New chat"
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    summary: str | None = Field(default=None, sa_type=Text)
    summary_through_run_id: uuid.UUID | None = None


class Run(SQLModel, table=True):
    """One agent run inside a thread; stores the messages the run produced."""

    __tablename__ = "runs"

    id: uuid.UUID = Field(default_factory=_uuid, primary_key=True)
    thread_id: uuid.UUID = Field(foreign_key="threads.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id")
    status: RunStatus = Field(default=RunStatus.RUNNING, sa_type=_enum(RunStatus))
    messages: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    usage: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
    finished_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
