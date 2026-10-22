from urllib.parse import parse_qs

import httpx
import pytest
from chat_models import Scripted
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, IdToken, backdate, chat, login_apple, login_google, sql
from pydantic import HttpUrl

from linguini.app import create_app
from linguini.auth import apple
from linguini.auth.oidc import sha256_hex
from linguini.config import Settings

pytestmark = pytest.mark.usefixtures("providers")


def test_delete_revokes_apple_with_the_stored_token_and_client(
    client: TestClient, settings: Settings, providers
) -> None:
    login_apple(client, "apple-ada")
    assert client.delete("/api/me", headers=CSRF_HEADERS).status_code == 204
    revoke = providers.post(apple.REVOKE_URL)
    assert revoke.call_count == 1
    form = parse_qs(revoke.calls[0].request.content.decode())
    assert form["token"] == ["apple-refresh-apple-ada"] and form["token_type_hint"] == ["refresh_token"]
    assert form["client_id"] == ["com.example.web"]
    assert client.get("/api/me").status_code == 401
    assert client.delete("/api/me", headers=CSRF_HEADERS).status_code == 401
    assert sql(settings.database_path, "SELECT COUNT(*) FROM identities") == [(0,)]
    assert sql(settings.database_path, "SELECT display_name FROM users WHERE deleted_at IS NOT NULL") == [
        ("Deleted user",)
    ]


def test_native_apple_revoke_uses_bundle_id_and_kills_every_session(
    client, settings: Settings, providers, id_token: IdToken
):
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    token = id_token("apple", "apple-ios", sha256_hex(nonce), aud="com.example.ios")
    body = {"id_token": token, "nonce": nonce, "authorization_code": "apple:apple-ios:x"}
    bearer = {"Authorization": f"Bearer {client.post('/api/auth/apple/native', json=body).json()['session_token']}"}
    second = client.post("/api/auth/nonce").json()["nonce"]
    body = {"id_token": id_token("apple", "apple-ios", sha256_hex(second), aud="com.example.ios"), "nonce": second}
    other = {"Authorization": f"Bearer {client.post('/api/auth/apple/native', json=body).json()['session_token']}"}
    assert client.delete("/api/me", headers=bearer).status_code == 204
    form = parse_qs(providers.post(apple.REVOKE_URL).calls[0].request.content.decode())
    assert form["client_id"] == ["com.example.ios"]
    assert client.get("/api/me", headers=bearer).status_code == 401
    assert client.get("/api/me", headers=other).status_code == 401


def test_delete_leaves_households_and_keeps_shared_history(settings: Settings) -> None:
    scripted = Scripted()
    app = create_app(settings, model=scripted.model())
    with TestClient(app) as client:
        login_google(client, "ada")
        alone = client.post("/api/households", json={"name": "Alone"}, headers=CSRF_HEADERS).json()["id"]
        shared = client.post("/api/households", json={"name": "Shared"}, headers=CSRF_HEADERS).json()["id"]
        invite = client.post(f"/api/households/{shared}/invites", headers=CSRF_HEADERS).json()
        bob = TestClient(app)
        login_google(bob, "bob", invite=invite["code"])
        rice = {"name": "rizs", "quantity": 1, "unit": "kg"}
        client.post(f"/api/households/{alone}/items", json=rice, headers=CSRF_HEADERS)
        client.post(f"/api/households/{shared}/items", json=rice, headers=CSRF_HEADERS)
        thread = client.post(f"/api/households/{shared}/threads", json={}, headers=CSRF_HEADERS).json()["id"]
        chat(client, shared, thread, "ate 200 g rizs")
        recipe = {"title": "R", "ingredients": [{"name": "rizs", "quantity": 1, "unit": "kg"}]}
        client.post(f"/api/households/{shared}/recipes", json=recipe, headers=CSRF_HEADERS)

        assert client.delete("/api/me", headers=CSRF_HEADERS).status_code == 204
        assert sql(settings.database_path, "SELECT COUNT(*) FROM households") == [(1,)]
        assert sql(settings.database_path, "SELECT name FROM inventory_items") == [("rizs",)]
        assert [m["display_name"] for m in bob.get(f"/api/households/{shared}/members").json()] == ["Bob"]
        detail = bob.get(f"/api/households/{shared}/threads/{thread}").json()
        roles = [m["role"] for m in detail["messages"]]
        assert roles[0] == "user" and "assistant" in roles
        assert len(bob.get(f"/api/households/{shared}/events").json()) == 2
        assert [r["title"] for r in bob.get(f"/api/households/{shared}/recipes").json()] == ["R"]
        assert "history=" in chat(bob, shared, thread, "still works")


def test_relogin_after_delete_needs_an_invite_and_gets_a_new_account(client: TestClient) -> None:
    login_google(client, "ada")
    old_id = client.get("/api/me").json()["id"]
    shared = client.post("/api/households", json={"name": "Shared"}, headers=CSRF_HEADERS).json()["id"]
    invite = client.post(f"/api/households/{shared}/invites", headers=CSRF_HEADERS).json()
    bob = TestClient(client.app)
    login_google(bob, "bob", invite=invite["code"])
    new_invite = bob.post(f"/api/households/{shared}/invites", headers=CSRF_HEADERS).json()
    client.delete("/api/me", headers=CSRF_HEADERS)
    again = TestClient(client.app)
    response = login_google(again, "ada")
    assert response.status_code == 403 and response.json()["detail"] == "invite_required"
    assert login_google(again, "ada", invite=new_invite["code"]).status_code == 303
    assert again.get("/api/me").json()["id"] != old_id


def test_sole_user_can_start_over_after_delete(client: TestClient) -> None:
    login_google(client, "ada")
    client.delete("/api/me", headers=CSRF_HEADERS)
    again = TestClient(client.app)
    assert login_google(again, "ada").status_code == 303
    assert again.get("/api/me").json()["display_name"] == "Ada"


@pytest.mark.parametrize("failure", [httpx.ConnectError("down"), httpx.Response(400, json={"error": "invalid_client"})])
def test_delete_survives_revoke_failure(client: TestClient, providers, failure) -> None:
    if isinstance(failure, httpx.Response):
        providers.post(apple.REVOKE_URL).mock(return_value=failure)
    else:
        providers.post(apple.REVOKE_URL).mock(side_effect=failure)
    login_apple(client, "apple-ada")
    assert client.delete("/api/me", headers=CSRF_HEADERS).status_code == 204
    assert client.get("/api/me").status_code == 401


def test_delete_skips_revoke_when_apple_is_not_configured(client: TestClient, settings: Settings, providers) -> None:
    login_apple(client, "apple-ada")
    settings.apple_services_id = None
    assert client.delete("/api/me", headers=CSRF_HEADERS).status_code == 204
    assert providers.post(apple.REVOKE_URL).call_count == 0


def test_startup_sweep_keeps_live_rows(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        login_google(client, "alice")
        home = client.post("/api/households", json={"name": "H"}, headers=CSRF_HEADERS).json()["id"]
        invite = client.post(f"/api/households/{home}/invites", headers=CSRF_HEADERS).json()["code"]
        client.get("/api/auth/google/start", follow_redirects=False)
        backdate(settings.database_path, "sessions", "expires_at", "-1 minute")
        backdate(settings.database_path, "oauth_states", "expires_at", "-1 minute")
        fresh = TestClient(client.app)
        login_google(fresh, "bob", invite=invite)
        fresh.get("/api/auth/apple/start", follow_redirects=False)
    with TestClient(create_app(settings)):
        pass
    assert sql(settings.database_path, "SELECT COUNT(*) FROM sessions") == [(1,)]
    assert sql(settings.database_path, "SELECT COUNT(*) FROM oauth_states") == [(1,)]


def test_tracing_is_per_app_and_off_by_default(settings: Settings) -> None:
    app = create_app(settings)
    assert app.state.tracer_provider is None
    settings.otel_endpoint = HttpUrl("http://127.0.0.1:4318/v1/traces")
    traced: FastAPI = create_app(settings)
    assert traced.state.tracer_provider is not None
    from opentelemetry import trace

    assert trace.get_tracer_provider() is not traced.state.tracer_provider
    with TestClient(traced):
        pass
