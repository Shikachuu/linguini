import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import ModelMessage
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models import Model

from linguini.chat.agent import build_summarizer, session_settings
from linguini.chat.history import SUMMARY_LIMITS, render_for_summary, summary_prompt
from linguini.config import Settings


class Line(BaseModel):
    role: Literal["user", "assistant", "call", "result"]
    text: str = ""
    tool: str = ""
    args: dict[str, Any] = {}


class SummaryInputs(BaseModel):
    conversation: list[Line]
    previous: str | None = None


def summary_task(model: Model, settings: Settings) -> Callable[[SummaryInputs], Awaitable[str]]:
    summarizer = build_summarizer(model)

    async def run(inputs: SummaryInputs) -> str:
        prompt = summary_prompt(inputs.previous, render_for_summary(_messages(inputs.conversation)))
        result = await summarizer.run(
            prompt, usage_limits=SUMMARY_LIMITS, model_settings=session_settings(settings, f"{uuid.uuid7()}:summary")
        )
        return result.output

    return run


def _messages(lines: list[Line]) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for index, line in enumerate(lines):
        call_id = f"call-{index}"
        match line.role:
            case "user":
                messages.append(ModelRequest(parts=[UserPromptPart(line.text)]))
            case "assistant":
                messages.append(ModelResponse(parts=[TextPart(line.text)]))
            case "call":
                messages.append(ModelResponse(parts=[ToolCallPart(line.tool, line.args, tool_call_id=call_id)]))
            case "result":
                messages.append(ModelRequest(parts=[ToolReturnPart(line.tool, line.text, tool_call_id=call_id)]))
    return messages
