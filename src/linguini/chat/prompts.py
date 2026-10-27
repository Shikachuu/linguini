"""Prompt files for the household agent and the summarizer."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import TemplateStr

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
CHAT_SPEC = PROMPTS_DIR / "chat.yaml"
SUMMARY_SPEC = PROMPTS_DIR / "summary.yaml"
REPLY_LANGUAGE = (PROMPTS_DIR / "reply_language.md").read_text(encoding="utf-8").strip()


class ChatContext(BaseModel):
    """The per-run facts rendered into the chat agent's instructions."""

    today: str
    weekday: str
    locale: str
    household_name: str
    members: list[str]
    user_name: str
    inventory_snapshot: str = ""
    kifli_broken: bool = False
    kifli_missing: bool = False
    notes: list[str] = []


class SummaryInput(BaseModel):
    """The summarizer's user prompt: the earlier summary, if any, and the conversation text."""

    previous: str = ""
    conversation: str


def _template[T: BaseModel](name: str, context: type[T]) -> TemplateStr[T]:
    return TemplateStr((PROMPTS_DIR / name).read_text(encoding="utf-8"), deps_type=context)


CHAT_CONTEXT = _template("chat_context.hbs", ChatContext)
SUMMARY_INPUT = _template("summary_input.hbs", SummaryInput)
