"""Per-run dependencies shared by the agent and its tools."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from linguini.db import Database


@dataclass(slots=True)
class AgentDeps:
    """Everything a run needs to know about who is asking and where to write."""

    db: Database
    household_id: uuid.UUID
    household_name: str
    member_names: list[str]
    user_id: uuid.UUID
    user_name: str
    thread_id: uuid.UUID
    run_id: uuid.UUID
    now: datetime
    locale: str
    inventory_snapshot: str = ""
    kifli_connected: bool = False
    kifli_broken: bool = False
    extra_notes: list[str] = field(default_factory=list)
    undid_previous_turn: bool = False
