from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model

from linguini.chat.guard import build_gate, classify, earlier_exchange
from linguini.chat.redact import redact_text


class TopicInputs(BaseModel):
    message: str
    previous_question: str = ""
    previous_reply: str = ""


class GateCase(BaseModel):
    expect: Literal["allow", "block"]
    category: str


class TopicOutcome(BaseModel):
    off_topic: float | None = None
    attack: float | None = None
    language: str | None = None
    blocked: bool = False
    error: str | None = None


def topic_task(guard_model: Model) -> Callable[[TopicInputs], Awaitable[TopicOutcome]]:
    gate = build_gate(guard_model)

    async def run(inputs: TopicInputs) -> TopicOutcome:
        conversation = [
            ModelRequest(parts=[UserPromptPart(inputs.previous_question)]),
            ModelResponse(parts=[TextPart(inputs.previous_reply)]),
            ModelRequest(parts=[UserPromptPart(inputs.message)]),
        ]
        history = earlier_exchange(conversation) if inputs.previous_reply else []
        try:
            verdict = await classify(gate, redact_text(inputs.message), history)
        except Exception as e:
            return TopicOutcome(error=f"{type(e).__name__}: {e}")
        return TopicOutcome(
            off_topic=verdict.off_topic,
            attack=verdict.attack,
            language=verdict.language,
            blocked=verdict.block_reason() is not None,
        )

    return run
