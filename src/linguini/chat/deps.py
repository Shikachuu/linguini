"""Per-run dependencies shared by the agent and its tools."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from linguini.chat.prompts import ChatContext
from linguini.db import Database
from linguini.kifli.oauth import LiveConnection


@dataclass(slots=True)
class GuardState:
    """What the guardrails decided during one run."""

    off_topic: float | None = None
    attack: float | None = None
    language: str | None = None
    blocked: bool = False
    gate_failed: bool = False
    leaked: bool = False
    released: dict[int, str] = field(default_factory=dict)
    cut_index: int | None = None


def _name(text: str) -> str:
    return " ".join(text.replace("«", "").replace("»", "").split())[:80]


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
    kifli: LiveConnection | None = None
    kifli_broken: bool = False
    kifli_server: object | None = None
    extra_notes: list[str] = field(default_factory=list)
    undid_previous_turn: bool = False
    guard: GuardState = field(default_factory=GuardState)

    def prompt_context(self) -> ChatContext:
        """The facts about this run that the instructions mention.

        Returns:
            The context rendered into the chat instructions.
        """
        return ChatContext(
            today=self.now.strftime("%Y-%m-%d"),
            weekday=self.now.strftime("%A"),
            locale=self.locale,
            household_name=_name(self.household_name),
            members=[_name(m) for m in self.member_names],
            user_name=_name(self.user_name),
            inventory_snapshot=self.inventory_snapshot,
            kifli_broken=self.kifli_broken,
            kifli_missing=self.kifli is None and self.kifli_server is None,
            notes=self.extra_notes,
        )
