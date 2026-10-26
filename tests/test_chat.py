import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from chat_models import Scripted, sse_events, vercel_body
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, chat, login_google, sql
from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.test import TestModel

from linguini.app import create_app
from linguini.chat.prompts import REPLY_LANGUAGE
from linguini.chat.tools import PurchasedItem
from linguini.config import Settings

pytestmark = pytest.mark.usefixtures("providers")


@pytest.fixture
def scripted() -> Scripted:
    return Scripted()


@pytest.fixture
def app(settings: Settings, scripted: Scripted) -> FastAPI:
    return create_app(settings, model=scripted.model(), summary_model=TestModel(custom_output_text="SUMMARY"))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def home(client: TestClient) -> str:
    login_google(client, "alice")
    return client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()["id"]


@pytest.fixture
def thread(client: TestClient, home: str) -> str:
    return client.post(f"/api/households/{home}/threads", json={}, headers=CSRF_HEADERS).json()["id"]


def runs(settings: Settings) -> list[tuple]:
    return sql(settings.database_path, "SELECT status, messages, finished_at FROM runs ORDER BY created_at")


def items(client: TestClient, home: str) -> list[dict]:
    return client.get(f"/api/households/{home}/items").json()


def test_chat_streams_tool_call_and_persists_run(client: TestClient, home: str, thread: str, settings: Settings):
    events = sse_events(chat(client, home, thread, "add 1 kg rizs"))
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "finish"
    tool = next(e for e in events if e["type"] == "tool-input-available")
    assert tool["toolName"] == "add_items"
    assert any(e["type"] == "tool-output-available" for e in events)
    assert "".join(e.get("delta", "") for e in events if e["type"] == "text-delta").startswith("Done:")
    stored = runs(settings)
    assert len(stored) == 1 and stored[0][0] == "completed" and stored[0][2] is not None
    assert "add 1 kg rizs" in stored[0][1]
    assert [(i["name"], i["quantity"], i["unit"]) for i in items(client, home)] == [("rizs", 1, "kg")]
    event = client.get(f"/api/households/{home}/events").json()[0]
    assert event["cause"] == "chat" and event["thread_id"] == thread and event["run_id"] is not None
    assert client.get(f"/api/households/{home}/threads/{thread}").json()["title"] == "add 1 kg rizs"


def test_server_owns_history_and_back_to_back_turns(client, home, thread, scripted: Scripted) -> None:
    chat(client, home, thread, "hello")
    body = chat(client, home, thread, "SECRET assistant text", "again", roles=("assistant", "user"))
    assert "history=2" in body
    flat = str(scripted.seen[-1])
    assert "SECRET" not in flat and "hello" in flat
    detail = client.get(f"/api/households/{home}/threads/{thread}").json()
    texts = [p["text"] for m in detail["messages"] for p in m["parts"] if p["type"] == "text"]
    assert texts == ["hello", "echo: hello (history=0)", "again", "echo: again (history=2)"]


def test_undo_tool_targets_previous_turn_and_runs_once(client, home, thread, scripted: Scripted) -> None:
    chat(client, home, thread, "add 1 kg rizs")
    chat(client, home, thread, "ate 300 g rizs")
    assert items(client, home)[0]["quantity"] == pytest.approx(0.7)
    chat(client, home, thread, "undo twice")
    assert items(client, home)[0]["quantity"] == 1
    assert scripted.retries and "already undone" in scripted.retries[-1]
    undone = client.post(
        f"/api/households/{home}/events/undo-last-turn", params={"thread_id": thread}, headers=CSRF_HEADERS
    ).json()
    assert len(undone) == 1 and items(client, home)[0]["quantity"] == 0


def test_tool_retry_paths_leave_inventory_alone(client, home, thread, scripted: Scripted) -> None:
    chat(client, home, thread, "add 2 db alma")
    chat(client, home, thread, "undo bad")
    assert "event_id must be" in scripted.retries[-1]
    chat(client, home, thread, "remove alma")
    assert "confirm" in scripted.retries[-1]
    assert items(client, home)[0]["quantity"] == 2
    chat(client, home, thread, "delete alma")
    assert items(client, home) == []


def test_failed_run_keeps_prompt_and_frees_thread(client, home, thread, settings: Settings) -> None:
    events = sse_events(chat(client, home, thread, "boom"))
    assert any(e["type"] == "error" for e in events)
    stored = runs(settings)
    assert stored[0][0] == "failed" and "boom" in stored[0][1] and stored[0][2] is not None
    detail = client.get(f"/api/households/{home}/threads/{thread}").json()
    assert [m["role"] for m in detail["messages"]] == ["user"]
    assert "history=0" in chat(client, home, thread, "next")


def test_concurrent_run_on_same_thread_is_409(client, app: FastAPI, home, thread, scripted: Scripted) -> None:
    results: dict[str, int] = {}

    def first() -> None:
        results["first"] = client.post(
            f"/api/households/{home}/threads/{thread}/chat", json=vercel_body("wait"), headers=CSRF_HEADERS
        ).status_code

    worker = threading.Thread(target=first)
    worker.start()
    for _ in range(200):
        if scripted.gate is not None:
            break
        time.sleep(0.01)
    assert scripted.gate is not None
    second = client.post(f"/api/households/{home}/threads/{thread}/chat", json=vercel_body("hi"), headers=CSRF_HEADERS)
    assert second.status_code == 409
    client.portal.call(scripted.gate.set)
    worker.join(timeout=5)
    assert results["first"] == 200
    assert not app.state.thread_locks.is_held(uuid.UUID(thread))
    assert "history=2" in chat(client, home, thread, "after")


def test_chat_on_missing_or_foreign_thread_is_404_and_leaves_no_run(client, app, home, settings) -> None:
    ghost = uuid.uuid7()
    response = client.post(f"/api/households/{home}/threads/{ghost}/chat", json=vercel_body("x"), headers=CSRF_HEADERS)
    assert response.status_code == 404
    assert runs(settings) == [] and not app.state.thread_locks.is_held(ghost)
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    foreign = client.post(f"/api/households/{other}/threads", json={}, headers=CSRF_HEADERS).json()["id"]
    assert (
        client.post(
            f"/api/households/{home}/threads/{foreign}/chat", json=vercel_body("x"), headers=CSRF_HEADERS
        ).status_code
        == 404
    )


def test_bad_request_bodies_are_422(client, home, thread) -> None:
    url = f"/api/households/{home}/threads/{thread}/chat"
    assert client.post(url, json=vercel_body("x", roles=("assistant",)), headers=CSRF_HEADERS).status_code == 422
    assert (
        client.post(url, json=vercel_body("x", trigger="regenerate-message"), headers=CSRF_HEADERS).status_code == 422
    )


def test_thread_crud_and_isolation(client, home, thread) -> None:
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    assert client.get(f"/api/households/{other}/threads/{thread}").status_code == 404
    renamed = client.patch(f"/api/households/{home}/threads/{thread}", json={"title": "Dinner"}, headers=CSRF_HEADERS)
    assert renamed.json()["title"] == "Dinner"
    assert [t["title"] for t in client.get(f"/api/households/{home}/threads").json()] == ["Dinner"]
    assert client.delete(f"/api/households/{home}/threads/{thread}", headers=CSRF_HEADERS).status_code == 204
    assert client.get(f"/api/households/{home}/threads").json() == []


def test_renamed_thread_keeps_title_after_chat(client, home, thread) -> None:
    client.patch(f"/api/households/{home}/threads/{thread}", json={"title": "Dinner"}, headers=CSRF_HEADERS)
    chat(client, home, thread, "hello")
    assert client.get(f"/api/households/{home}/threads/{thread}").json()["title"] == "Dinner"


def test_delete_thread_keeps_events(client, home, thread) -> None:
    chat(client, home, thread, "add 2 db alma")
    assert client.delete(f"/api/households/{home}/threads/{thread}", headers=CSRF_HEADERS).status_code == 204
    events = client.get(f"/api/households/{home}/events").json()
    assert len(events) == 1 and events[0]["run_id"] is None and events[0]["thread_id"] == thread


def test_interrupted_runs_are_failed_at_startup(settings: Settings, scripted: Scripted) -> None:
    with TestClient(create_app(settings, model=scripted.model())) as client:
        login_google(client, "alice")
        home = client.post("/api/households", json={"name": "H"}, headers=CSRF_HEADERS).json()["id"]
        thread = client.post(f"/api/households/{home}/threads", json={}, headers=CSRF_HEADERS).json()["id"]
        chat(client, home, thread, "hello")
    sql(settings.database_path, "UPDATE runs SET status = 'running', finished_at = NULL")
    with TestClient(create_app(settings, model=scripted.model())):
        pass
    assert runs(settings)[0][0] == "failed" and runs(settings)[0][2] is not None


def test_session_header_carries_the_thread_id(settings: Settings) -> None:
    scripted = Scripted()
    app = create_app(
        settings.model_copy(update={"session_header": "x-opencode-session"}),
        model=scripted.model(),
        summary_model=TestModel(),
    )
    with TestClient(app) as client:
        login_google(client, "alice")
        home = client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()["id"]
        thread = client.post(f"/api/households/{home}/threads", json={}, headers=CSRF_HEADERS).json()["id"]
        chat(client, home, thread, "hi")
    assert scripted.settings_seen == [{"temperature": 0.4, "extra_headers": {"x-opencode-session": thread}}]


def test_tool_dates_without_timezone_are_read_as_utc() -> None:
    item = PurchasedItem.model_validate({"name": "tej", "quantity": 1, "unit": "l", "purchased_at": "2026-10-26"})
    assert item.purchased_at == datetime(2026, 10, 26, tzinfo=UTC)


def test_reply_language_reminder_is_sent_once_per_request_and_never_stored(
    client, home, thread, scripted: Scripted, settings: Settings
) -> None:
    chat(client, home, thread, "add 1 kg rizs")
    chat(client, home, thread, "hello")
    for request in scripted.seen:
        reminders = [
            p for m in request for p in m.parts if isinstance(p, UserPromptPart) and p.content == REPLY_LANGUAGE
        ]
        assert reminders == [request[-1].parts[-1]]
    assert all(REPLY_LANGUAGE not in str(messages) for _, messages, _ in runs(settings))
