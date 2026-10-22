import base64
import hashlib
import threading
import time
import uuid
from collections.abc import Iterator
from typing import cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
import uvicorn
from chat_models import Scripted, sse_events
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastmcp import FastMCP
from helpers import CSRF_HEADERS, backdate, chat, login_google, sql
from pydantic_ai.messages import ModelRequest
from pydantic_ai.models.test import TestModel

from linguini.app import create_app
from linguini.auth.crypto import decrypt
from linguini.config import Settings
from linguini.kifli import oauth

MCP_URL = "https://mcp.kifli.hu/mcp"
ISSUER = "https://identity.kifli.hu"

pytestmark = pytest.mark.usefixtures("providers", "shop")


@pytest.fixture
def shop(providers: respx.MockRouter) -> Iterator[dict]:
    state: dict = {"registrations": 0, "tokens": 0, "refreshes": 0, "refresh_ok": True, "challenge": None}
    providers.get("https://mcp.kifli.hu/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={"resource": MCP_URL, "authorization_servers": [ISSUER]})
    )
    providers.get(f"{ISSUER}/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(
            200,
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/oauth2/authorize",
                "token_endpoint": f"{ISSUER}/oauth2/token",
                "registration_endpoint": f"{ISSUER}/connect/register",
            },
        )
    )

    def register(request: httpx.Request) -> httpx.Response:
        state["registrations"] += 1
        body = {"client_id": "client-xyz", "redirect_uris": [oauth.REDIRECT_URI], "registration_access_token": "rat"}
        return httpx.Response(201, json=body)

    def token(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if form["grant_type"][0] == "refresh_token":
            state["refreshes"] += 1
            if not state["refresh_ok"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            refreshed = {"access_token": "at-refreshed", "refresh_token": "rt-2", "expires_in": 3600}
            return httpx.Response(200, json=refreshed)
        state["tokens"] += 1
        assert form["client_id"] == ["client-xyz"] and form["redirect_uri"] == [oauth.REDIRECT_URI]
        assert form["resource"] == [MCP_URL]
        digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
        assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == state["challenge"]
        issued = {"access_token": f"at-{form['code'][0]}", "refresh_token": "rt-1", "expires_in": 3600}
        return httpx.Response(200, json=issued)

    providers.post(f"{ISSUER}/connect/register").mock(side_effect=register)
    providers.post(f"{ISSUER}/oauth2/token").mock(side_effect=token)
    oauth._discoveries.clear()
    oauth._refresh_locks.clear()
    yield state


@pytest.fixture
def scripted() -> Scripted:
    return Scripted()


@pytest.fixture
def fake_server() -> FastMCP:
    server = FastMCP("fake-kifli")

    @server.tool
    def search_products(query: str) -> list[dict]:
        """Search the shop."""
        if query == "explode":
            raise ValueError("shop tool failed")
        return [{"id": "p1", "name": f"{query} 500 g", "price": 1290}]

    return server


@pytest.fixture
def client(settings: Settings, scripted: Scripted) -> Iterator[TestClient]:
    with TestClient(create_app(settings, model=scripted.model(), summary_model=TestModel())) as client:
        yield client


@pytest.fixture
def home(client: TestClient) -> str:
    login_google(client, "alice")
    return client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()["id"]


@pytest.fixture
def thread(client: TestClient, home: str) -> str:
    return client.post(f"/api/households/{home}/threads", json={}, headers=CSRF_HEADERS).json()["id"]


def start(client: TestClient, home: str, shop: dict) -> str:
    started = client.post(f"/api/households/{home}/kifli/connect", headers=CSRF_HEADERS)
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(started.json()["authorize_url"]).query)
    shop["challenge"] = query["code_challenge"][0]
    return query["state"][0]


def connect(client: TestClient, home: str, shop: dict, code: str = "abc") -> dict:
    state = start(client, home, shop)
    url = f"/api/households/{home}/kifli/callback"
    callback = f"{oauth.REDIRECT_URI}?code={code}&state={state}"
    finished = client.post(url, json={"callback_url": callback}, headers=CSRF_HEADERS)
    assert finished.status_code == 200, finished.text
    return finished.json()


def live(client: TestClient, settings: Settings, home: str) -> oauth.LiveConnection | oauth.ConnectionState:
    app = cast(FastAPI, client.app)
    assert client.portal is not None
    return client.portal.call(oauth.live_connection, app.state.db, app.state.http, settings, uuid.UUID(home))


def token_of(result: oauth.LiveConnection | oauth.ConnectionState) -> str:
    assert isinstance(result, oauth.LiveConnection)
    return result.access_token


def last_instructions(scripted: Scripted) -> str:
    last = scripted.seen[-1][-1]
    assert isinstance(last, ModelRequest)
    return str(last.instructions)


def test_connect_flow_registers_once_and_stores_encrypted_tokens(client, home, settings: Settings, shop) -> None:
    before = client.get(f"/api/households/{home}/kifli").json()
    assert before == {"connected": False, "broken": False, "mcp_url": None, "connected_at": None, "expires_at": None}
    started = client.post(f"/api/households/{home}/kifli/connect", headers=CSRF_HEADERS).json()
    query = parse_qs(urlsplit(started["authorize_url"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["resource"] == [MCP_URL]
    assert query["redirect_uri"] == [oauth.REDIRECT_URI] and "offline_access" in query["scope"][0]
    assert "paste" in started["instructions"]
    status = connect(client, home, shop)
    assert status["connected"] and not status["broken"] and status["mcp_url"] == MCP_URL
    assert shop["registrations"] == 1 and shop["tokens"] == 1
    stored = sql(settings.database_path, "SELECT access_token_enc, refresh_token_enc FROM kifli_connections")[0]
    assert decrypt(settings, stored[0]) == "at-abc" and decrypt(settings, stored[1]) == "rt-1"
    clients = sql(settings.database_path, "SELECT client_id, paste_only, registration FROM kifli_clients")
    assert clients[0][:2] == ("client-xyz", 1) and "rat" not in clients[0][2]
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    connect(client, other, shop)
    assert shop["registrations"] == 1


def test_callback_needs_code_and_state(client, home) -> None:
    url = f"/api/households/{home}/kifli/callback"
    no_state = {"callback_url": f"{oauth.REDIRECT_URI}?code=x"}
    assert client.post(url, json=no_state, headers=CSRF_HEADERS).status_code == 422
    bogus = {"callback_url": f"{oauth.REDIRECT_URI}?code=x&state=unknown"}
    assert client.post(url, json=bogus, headers=CSRF_HEADERS).status_code == 400


def test_callback_is_bound_to_household_and_single_use(client, home, shop) -> None:
    state = start(client, home, shop)
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    body = {"callback_url": f"{oauth.REDIRECT_URI}?code=x&state={state}"}
    assert client.post(f"/api/households/{other}/kifli/callback", json=body, headers=CSRF_HEADERS).status_code == 400
    url = f"/api/households/{home}/kifli/callback"
    assert client.post(url, json=body, headers=CSRF_HEADERS).status_code == 200
    assert client.post(url, json=body, headers=CSRF_HEADERS).status_code == 400
    assert shop["tokens"] == 1


def test_expired_state_does_not_spend_the_code(client, home, settings: Settings, shop) -> None:
    state = start(client, home, shop)
    backdate(settings.database_path, "oauth_states", "expires_at", "-1 minute")
    body = {"callback_url": f"{oauth.REDIRECT_URI}?code=x&state={state}"}
    assert client.post(f"/api/households/{home}/kifli/callback", json=body, headers=CSRF_HEADERS).status_code == 400
    assert shop["tokens"] == 0


def test_rejected_code_is_401_without_connection(client, home, shop, providers: respx.MockRouter) -> None:
    state = start(client, home, shop)
    providers.post(f"{ISSUER}/oauth2/token").mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    body = {"callback_url": f"{oauth.REDIRECT_URI}?code=x&state={state}"}
    assert client.post(f"/api/households/{home}/kifli/callback", json=body, headers=CSRF_HEADERS).status_code == 401
    assert client.get(f"/api/households/{home}/kifli").json()["connected"] is False
    providers.post(f"{ISSUER}/oauth2/token").mock(side_effect=httpx.ConnectError("down"))
    state = start(client, home, shop)
    body = {"callback_url": f"{oauth.REDIRECT_URI}?code=x&state={state}"}
    assert client.post(f"/api/households/{home}/kifli/callback", json=body, headers=CSRF_HEADERS).status_code == 502


def test_disconnect(client, home, settings: Settings, shop) -> None:
    assert client.delete(f"/api/households/{home}/kifli", headers=CSRF_HEADERS).status_code == 204
    connect(client, home, shop)
    assert client.delete(f"/api/households/{home}/kifli", headers=CSRF_HEADERS).status_code == 204
    assert client.get(f"/api/households/{home}/kifli").json()["connected"] is False
    assert sql(settings.database_path, "SELECT COUNT(*) FROM kifli_connections")[0][0] == 0


@pytest.mark.parametrize(
    ("url", "response"),
    [
        ("https://mcp.kifli.hu/.well-known/oauth-protected-resource/mcp", httpx.Response(500)),
        ("https://mcp.kifli.hu/.well-known/oauth-protected-resource/mcp", httpx.Response(200, json={})),
        (f"{ISSUER}/.well-known/oauth-authorization-server", httpx.Response(200, json={"issuer": ISSUER})),
        (f"{ISSUER}/connect/register", httpx.Response(400, json={"error": "invalid_request"})),
    ],
)
def test_discovery_and_registration_failures_are_502(client, home, providers, url: str, response) -> None:
    providers.get(url).mock(return_value=response) if "well-known" in url else providers.post(url).mock(
        return_value=response
    )
    assert client.post(f"/api/households/{home}/kifli/connect", headers=CSRF_HEADERS).status_code == 502
    assert MCP_URL not in oauth._discoveries or "register" in url


def test_live_connection_refreshes_and_marks_broken_only_on_invalid_grant(client, home, settings, shop) -> None:
    connect(client, home, shop)
    assert token_of(live(client, settings, home)) == "at-abc" and shop["refreshes"] == 0
    backdate(settings.database_path, "kifli_connections", "expires_at", "-1 minute")
    assert token_of(live(client, settings, home)) == "at-refreshed" and shop["refreshes"] == 1
    stored = sql(settings.database_path, "SELECT refresh_token_enc FROM kifli_connections")[0][0]
    assert decrypt(settings, stored) == "rt-2"
    backdate(settings.database_path, "kifli_connections", "expires_at", "-1 minute")
    shop["refresh_ok"] = False
    assert live(client, settings, home) is oauth.ConnectionState.BROKEN
    assert client.get(f"/api/households/{home}/kifli").json()["broken"] is True
    assert live(client, settings, home) is oauth.ConnectionState.BROKEN and shop["refreshes"] == 2
    shop["refresh_ok"] = True
    connect(client, home, shop)
    assert client.get(f"/api/households/{home}/kifli").json()["broken"] is False


def test_transient_refresh_failure_is_unavailable_not_broken(client, home, settings, shop, providers) -> None:
    connect(client, home, shop)
    backdate(settings.database_path, "kifli_connections", "expires_at", "-1 minute")
    providers.post(f"{ISSUER}/oauth2/token").mock(return_value=httpx.Response(503))
    assert live(client, settings, home) is oauth.ConnectionState.UNAVAILABLE
    providers.post(f"{ISSUER}/oauth2/token").mock(side_effect=httpx.ConnectError("down"))
    assert live(client, settings, home) is oauth.ConnectionState.UNAVAILABLE
    assert client.get(f"/api/households/{home}/kifli").json()["broken"] is False


def test_missing_refresh_token_marks_broken(client, home, settings, shop, providers) -> None:
    def no_refresh(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at-only", "expires_in": 3600})

    providers.post(f"{ISSUER}/oauth2/token").mock(side_effect=no_refresh)
    state = start(client, home, shop)
    body = {"callback_url": f"{oauth.REDIRECT_URI}?code=x&state={state}"}
    assert client.post(f"/api/households/{home}/kifli/callback", json=body, headers=CSRF_HEADERS).status_code == 200
    backdate(settings.database_path, "kifli_connections", "expires_at", "-1 minute")
    assert live(client, settings, home) is oauth.ConnectionState.BROKEN


def test_chat_states_reach_the_agent(client, home, thread, settings, shop, scripted: Scripted, providers) -> None:
    chat(client, home, thread, "shop rizs")
    assert "Kifli is not connected" in last_instructions(scripted)
    connect(client, home, shop)
    backdate(settings.database_path, "kifli_connections", "expires_at", "-1 minute")
    providers.post(f"{ISSUER}/oauth2/token").mock(return_value=httpx.Response(503))
    body = chat(client, home, thread, "shop rizs")
    assert "temporarily unreachable" in last_instructions(scripted)
    assert "at-abc" not in body
    providers.post(f"{ISSUER}/oauth2/token").mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    chat(client, home, thread, "shop rizs")
    assert "Kifli is disconnected" in last_instructions(scripted)


@pytest.fixture
def served(fake_server: FastMCP) -> Iterator[tuple[str, list[str]]]:
    seen_auth: list[str] = []
    inner = fake_server.http_app(path="/mcp")

    async def app(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode(): v.decode() for k, v in scope["headers"]}
            seen_auth.append(headers.get("authorization", ""))
        await inner(scope, receive, send)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/mcp", seen_auth
    server.should_exit = True
    worker.join(timeout=5)


def test_connected_chat_sends_bearer_to_mcp_and_never_stores_it(
    client, home, thread, settings: Settings, shop, served: tuple[str, list[str]]
) -> None:
    connect(client, home, shop)
    url, seen_auth = served
    sql(settings.database_path, "UPDATE kifli_connections SET mcp_url = ?", url)
    body = chat(client, home, thread, "shop rizs")
    assert seen_auth and all(a == "Bearer at-abc" for a in seen_auth)
    assert "rizs 500 g" in body
    assert "at-abc" not in body and "rt-1" not in body
    stored = sql(settings.database_path, "SELECT messages FROM runs")
    assert stored and all("at-abc" not in (row[0] or "") for row in stored)
    assert "at-abc" not in client.get(f"/api/households/{home}/kifli").text


def test_unreachable_mcp_server_fails_the_run_but_not_the_thread(client, home, thread, settings, shop) -> None:
    connect(client, home, shop)
    sql(settings.database_path, "UPDATE kifli_connections SET mcp_url = ?", "http://127.0.0.1:1/mcp")
    body = chat(client, home, thread, "shop rizs")
    assert any(e["type"] == "error" for e in sse_events(body))
    assert sql(settings.database_path, "SELECT status FROM runs ORDER BY created_at")[-1][0] == "failed"
    sql(settings.database_path, "DELETE FROM kifli_connections")
    assert "history=" in chat(client, home, thread, "after")


def test_failing_shop_tool_does_not_kill_the_run(
    client, home, thread, scripted: Scripted, fake_server: FastMCP
) -> None:
    client.app.state.kifli_server = fake_server
    body = chat(client, home, thread, "shop explode")
    events = sse_events(body)
    assert any(e["type"] in {"tool-output-error", "tool-output-available"} for e in events)
    assert "shop tool failed" in body
    assert "history=" in chat(client, home, thread, "after")


def test_chat_uses_shop_tools_when_connected(client, home, thread, scripted: Scripted, fake_server: FastMCP) -> None:
    client.app.state.kifli_server = fake_server
    body = chat(client, home, thread, "shop rizs")
    tool = next(e for e in sse_events(body) if e["type"] == "tool-input-available")
    assert tool["toolName"] == "kifli_search_products"
    assert "rizs 500 g" in body
    assert "Kifli is not connected" not in last_instructions(scripted)


def test_parse_callback_url_accepts_full_url_only() -> None:
    assert oauth.parse_callback_url(f" {oauth.REDIRECT_URI}?state=s&code=c ") == ("c", "s")
    with pytest.raises(HTTPException) as exc:
        oauth.parse_callback_url("c")
    assert exc.value.status_code == 422
