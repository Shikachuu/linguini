import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryFeedbackPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from linguini.chat.prompts import REPLY_LANGUAGE


def last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if (
                    isinstance(part, UserPromptPart)
                    and isinstance(part.content, str)
                    and part.content != REPLY_LANGUAGE
                ):
                    return part.content
    return ""


def tool_returns(message: ModelMessage) -> list[ToolReturnPart]:
    if not isinstance(message, ModelRequest):
        return []
    return [p for p in message.parts if isinstance(p, ToolReturnPart) and p.outcome != "retried"]


def retry_parts(message: ModelMessage) -> list[ToolReturnPart | RetryFeedbackPart]:
    if not isinstance(message, ModelRequest):
        return []
    return [
        p
        for p in message.parts
        if isinstance(p, RetryFeedbackPart) or (isinstance(p, ToolReturnPart) and p.outcome == "retried")
    ]


def call(name: str, args: dict, call_id: str) -> DeltaToolCalls:
    return {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id=call_id)}


def streamed(respond: Callable[[list[ModelMessage], AgentInfo], ModelResponse]) -> FunctionModel:
    """A FunctionModel that also streams, as the guarded chat agent always streams."""

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        for index, part in enumerate(respond(messages, info).parts):
            await asyncio.sleep(0)
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id=part.tool_call_id
                    )
                }

    return FunctionModel(respond, stream_function=stream)


def amount(text: str) -> dict:
    qty, unit, name = text.split(" ", 2)
    return {"items": [{"name": name, "quantity": float(qty), "unit": unit}]}


@dataclass
class Scripted:
    seen: list[list[ModelMessage]] = field(default_factory=list)
    retries: list[str] = field(default_factory=list)
    gate: asyncio.Event | None = None
    settings_seen: list[object] = field(default_factory=list)

    async def stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        self.seen.append(list(messages))
        self.settings_seen.append(info.model_settings)
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
            if returns[0].tool_name == "list_recipes" and prompt.startswith("cook "):
                found = returns[0].content
                if isinstance(found, list) and found:
                    yield call("cook_recipe", {"recipe_id": found[0]["id"], "servings": 4}, "call-cook")
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
        elif prompt.startswith("save "):
            recipe = {
                "title": prompt[5:],
                "servings": 2,
                "ingredients": [
                    {"name": "rizs", "quantity": 200, "unit": "g"},
                    {"name": "vaj", "quantity": 20, "unit": "g", "optional": True},
                ],
                "steps": ["cook"],
                "allergens": ["dairy"],
            }
            yield call("save_recipe", {"recipe": recipe}, "call-save")
        elif prompt.startswith("cook id "):
            yield call("cook_recipe", {"recipe_id": prompt[8:]}, "call-cook-id")
        elif prompt.startswith("cook big "):
            yield call("cook_recipe", {"recipe_id": prompt[9:], "servings": 1000}, "call-cook-big")
        elif prompt.startswith("cook "):
            yield call("list_recipes", {"query": prompt[5:]}, "call-list")
        elif prompt.startswith("recipe "):
            yield call("get_recipe", {"recipe_id": prompt[7:]}, "call-get")
        elif prompt.startswith("shop "):
            tools = {t.name for t in info.function_tools}
            if "kifli_search_products" in tools:
                yield call("kifli_search_products", {"query": prompt[5:]}, "call-shop")
            else:
                yield f"shop tools: {sorted(t for t in tools if t.startswith('kifli'))} not connected"
        elif prompt == "list":
            yield call("list_items", {}, "call-list-items")
        elif prompt.startswith("say "):
            text, _, add = prompt[4:].partition(" && add ")
            for chunk in text.split("|"):
                yield chunk
            if add:
                yield call("add_items", amount(add), "call-add-after-text")
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


def gate_model(
    off_topic: float = 0.0, attack: float = 0.0, language: str = "en", *, seen: list[str] | None = None
) -> FunctionModel:
    """A stand-in for the decision model behind the topic gate, answering with a fixed verdict."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(last_user_text(messages))
        verdict = {"off_topic": off_topic, "attack": attack, "language": language}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, verdict)])

    return FunctionModel(respond, model_name="gate")


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
