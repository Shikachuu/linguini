import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelRequest, RetryPromptPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel


def last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return ""


def tool_returns(message: ModelMessage) -> list[ToolReturnPart]:
    if not isinstance(message, ModelRequest):
        return []
    return [p for p in message.parts if isinstance(p, ToolReturnPart)]


def retry_parts(message: ModelMessage) -> list[RetryPromptPart]:
    if not isinstance(message, ModelRequest):
        return []
    return [p for p in message.parts if isinstance(p, RetryPromptPart)]


def call(name: str, args: dict, call_id: str) -> DeltaToolCalls:
    return {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id=call_id)}


def amount(text: str) -> dict:
    qty, unit, name = text.split(" ", 2)
    return {"items": [{"name": name, "quantity": float(qty), "unit": unit}]}


@dataclass
class Scripted:
    seen: list[list[ModelMessage]] = field(default_factory=list)
    retries: list[str] = field(default_factory=list)
    gate: asyncio.Event | None = None

    async def stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        self.seen.append(list(messages))
        prompt = last_user_text(messages)
        last = messages[-1]
        if retries := retry_parts(last):
            content = retries[0].content
            self.retries.append(content if isinstance(content, str) else json.dumps(content))
            yield "Retry seen: "
            yield self.retries[-1][:80]
            return
        if returns := tool_returns(last):
            undo_calls = sum(1 for m in messages for p in tool_returns(m) if p.tool_name == "undo")
            if prompt == "undo twice" and undo_calls == 1:
                yield call("undo", {}, "call-undo-2")
                return
            yield "Done: "
            yield str(returns[0].content)[:80]
            return
        if prompt.startswith("add "):
            yield call("add_items", amount(prompt[4:]), "call-add")
        elif prompt.startswith("ate "):
            yield call("consume_items", amount(prompt[4:]), "call-eat")
        elif prompt in {"undo", "undo twice"}:
            yield call("undo", {}, "call-undo")
        elif prompt == "undo bad":
            yield call("undo", {"event_id": "nope"}, "call-undo-bad")
        elif prompt.startswith("remove "):
            yield call("remove_item", {"name": prompt[7:], "user_confirmed": False}, "call-remove")
        elif prompt.startswith("delete "):
            yield call("remove_item", {"name": prompt[7:], "user_confirmed": True}, "call-delete")
        elif prompt == "wait":
            self.gate = asyncio.Event()
            yield "waiting..."
            await self.gate.wait()
            yield "released"
        elif prompt == "boom":
            yield "partial "
            raise RuntimeError("model exploded")
        else:
            yield f"echo: {prompt} (history={len(messages) - 1})"

    def model(self) -> FunctionModel:
        return FunctionModel(stream_function=self.stream, model_name="scripted")


def vercel_body(*texts: str, roles: tuple[str, ...] | None = None, trigger: str = "submit-message") -> dict:
    roles = roles or tuple("user" for _ in texts)
    body = {
        "trigger": trigger,
        "id": "chat-1",
        "messages": [
            {"id": f"m{i}", "role": role, "parts": [{"type": "text", "text": text}]}
            for i, (text, role) in enumerate(zip(texts, roles, strict=True))
        ],
    }
    if trigger == "regenerate-message":
        body["messageId"] = "m0"
    return body


def sse_events(body: str) -> list[dict]:
    lines = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
    return [json.loads(line) for line in lines if line != "[DONE]"]
