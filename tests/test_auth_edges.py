import time

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, IdToken, backdate, fake_code, login_apple, login_google, sql, start_login

from linguini.auth import google
from linguini.auth.crypto import decrypt
from linguini.auth.oidc import sha256_hex
from linguini.config import Settings

pytestmark = pytest.mark.usefixtures("providers")


def test_stale_session_on_write_route_does_not_deadlock(client: TestClient, settings: Settings) -> None:
    login_google(client, "alice")
    backdate(settings.database_path, "sessions", "last_seen_at", "-2 hours")
    before = sql(settings.database_path, "SELECT last_seen_at FROM sessions")[0][0]
    assert client.get("/api/auth/apple/start", follow_redirects=False).status_code == 303
    for _ in range(50):
        after = sql(settings.database_path, "SELECT last_seen_at FROM sessions")[0][0]
        if after != before:
            break
        time.sleep(0.05)
    assert after != before


def test_recent_session_is_not_rewritten(client: TestClient, settings: Settings) -> None:
    login_google(client, "alice")
    backdate(settings.database_path, "sessions", "last_seen_at", "-10 minutes")
    before = sql(settings.database_path, "SELECT last_seen_at FROM sessions")[0][0]
    client.get("/api/me")
    time.sleep(0.2)
    assert sql(settings.database_path, "SELECT last_seen_at FROM sessions")[0][0] == before


def test_expired_session_is_rejected(client: TestClient, settings: Settings) -> None:
    login_google(client, "alice")
    backdate(settings.database_path, "sessions", "expires_at", "-1 minute")
    assert client.get("/api/me").status_code == 401


def test_idle_session_is_rejected(client: TestClient, settings: Settings) -> None:
    login_google(client, "alice")
    backdate(settings.database_path, "sessions", "last_seen_at", "-15 days")
    assert client.get("/api/me").status_code == 401


def test_expired_state_is_rejected(client: TestClient, settings: Settings) -> None:
    state, nonce = start_login(client, "google")
    backdate(settings.database_path, "oauth_states", "expires_at", "-1 minute")
    params = {"state": state, "code": fake_code("google", "alice", nonce)}
    assert client.get("/api/auth/google/callback", params=params).status_code == 400


def test_expired_state_rows_are_purged_on_next_start(client: TestClient, settings: Settings) -> None:
    start_login(client, "google")
    backdate(settings.database_path, "oauth_states", "expires_at", "-1 minute")
    start_login(client, "google")
    assert sql(settings.database_path, "SELECT COUNT(*) FROM oauth_states")[0][0] == 1


def test_expired_invite_is_useless(client: TestClient, settings: Settings) -> None:
    login_google(client, "alice")
    household = client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    invite = client.post(f"/api/households/{household['id']}/invites", headers=CSRF_HEADERS).json()
    backdate(settings.database_path, "invites", "expires_at", "-1 minute")
    bob = TestClient(client.app)
    assert login_google(bob, "bob", invite=invite["code"]).status_code == 403


def test_expired_nonce_is_rejected(client: TestClient, settings: Settings, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    backdate(settings.database_path, "oauth_states", "expires_at", "-1 minute")
    body = {"id_token": id_token("google", "alice", nonce), "nonce": nonce}
    assert client.post("/api/auth/google/native", json=body).status_code == 400


@pytest.mark.parametrize(
    "target", ["//evil.example", "/\\evil.example", "/ok\r\nSet-Cookie: x=1", "javascript:alert(1)"]
)
def test_return_to_rejects_unsafe_targets(client: TestClient, target: str) -> None:
    assert login_google(client, "alice", return_to=target).headers["location"] == "/"


def test_return_to_keeps_relative_path(client: TestClient) -> None:
    assert login_google(client, "alice", return_to="/households/1?tab=x").headers["location"] == "/households/1?tab=x"


def test_provider_error_is_url_encoded(client: TestClient) -> None:
    state, _ = start_login(client, "google")
    params = {"state": state, "error": "access_denied&admin=1"}
    response = client.get("/api/auth/google/callback", params=params, follow_redirects=False)
    assert response.headers["location"] == "/?login_error=access_denied%26admin%3D1"


def test_token_endpoint_failure_is_401_without_upstream_text(client: TestClient, providers) -> None:
    providers.post(google.TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant SECRET"}))
    state, nonce = start_login(client, "google")
    response = client.get("/api/auth/google/callback", params={"state": state, "code": fake_code("google", "a", nonce)})
    assert response.status_code == 401
    assert "SECRET" not in response.text


def test_wrong_audience_is_rejected(client: TestClient, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    body = {"id_token": id_token("google", "alice", nonce, aud="someone-else"), "nonce": nonce}
    assert client.post("/api/auth/google/native", json=body).status_code == 401


def test_jwks_refetch_is_throttled(client: TestClient, id_token: IdToken, providers) -> None:
    import jwt

    nonce = client.post("/api/auth/nonce").json()["nonce"]
    good = id_token("google", "alice", nonce)
    client.post("/api/auth/google/native", json={"id_token": good, "nonce": nonce})
    for _ in range(3):
        n = client.post("/api/auth/nonce").json()["nonce"]
        bad = jwt.encode({"sub": "x", "nonce": n}, "s" * 32, algorithm="HS256", headers={"kid": "unknown"})
        client.post("/api/auth/google/native", json={"id_token": bad, "nonce": n})
    assert providers.get(google.JWKS_URL).call_count == 1


def test_csrf_cross_site_with_header_is_rejected(client: TestClient) -> None:
    login_google(client, "alice")
    cross = {"X-Requested-With": "linguini", "Sec-Fetch-Site": "cross-site", "Origin": "http://localhost:8000"}
    assert client.post("/api/households", json={"name": "X"}, headers=cross).status_code == 403
    wrong = {"X-Requested-With": "nope", "Sec-Fetch-Site": "same-origin"}
    assert client.post("/api/households", json={"name": "X"}, headers=wrong).status_code == 403


def test_csrf_covers_patch_and_delete(client: TestClient) -> None:
    login_google(client, "alice")
    household = client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    assert client.patch(f"/api/households/{household['id']}", json={"name": "Y"}).status_code == 403
    assert client.delete(f"/api/households/{household['id']}").status_code == 403


def test_csrf_exempts_apple_callback_and_ignores_other_cookies(client: TestClient) -> None:
    login_google(client, "alice")
    state, _ = start_login(client, "apple")
    response = client.post("/api/auth/apple/callback", data={"state": state, "error": "x"}, follow_redirects=False)
    assert response.status_code == 303
    client.cookies.clear()
    client.cookies.set("xsid", "decoy")
    assert client.post("/api/auth/nonce").status_code == 200


def test_link_conflict_is_409_and_link_sets_no_cookie(client: TestClient) -> None:
    login_google(client, "alice")
    login_apple(client, "apple-shared")
    bob = TestClient(client.app)
    invite_owner = client.post("/api/households", json={"name": "H"}, headers=CSRF_HEADERS).json()
    invite = client.post(f"/api/households/{invite_owner['id']}/invites", headers=CSRF_HEADERS).json()
    login_google(bob, "bob", invite=invite["code"])
    assert login_apple(bob, "apple-shared").status_code == 409
    again = login_apple(client, "apple-shared")
    assert again.status_code == 303
    assert "set-cookie" not in again.headers or "sid=" not in again.headers.get("set-cookie", "")


def test_native_apple_stores_encrypted_refresh_token(client: TestClient, settings: Settings, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    token = id_token("apple", "apple-ios", sha256_hex(nonce), aud="com.example.ios")
    body = {"id_token": token, "nonce": nonce, "authorization_code": fake_code("apple", "apple-ios", nonce)}
    response = client.post("/api/auth/apple/native", json=body)
    assert response.status_code == 200, response.text
    stored = sql(settings.database_path, "SELECT apple_refresh_token_enc FROM identities")[0][0]
    assert stored != "apple-refresh-apple-ios"
    assert decrypt(settings, stored) == "apple-refresh-apple-ios"


def test_hashed_nonce_only_for_apple(client: TestClient, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    body = {"id_token": id_token("google", "alice", sha256_hex(nonce)), "nonce": nonce}
    assert client.post("/api/auth/google/native", json=body).status_code == 401


def test_notification_keeps_user_with_other_identity(client: TestClient, id_token: IdToken) -> None:
    login_google(client, "alice")
    login_apple(client, "apple-alice")
    payload = id_token("apple", "x", "n", events={"type": "account-deleted", "sub": "apple-alice"})
    assert client.post("/api/auth/apple/notifications", json={"payload": payload}).status_code == 204
    me = client.get("/api/me").json()
    assert [i["provider"] for i in me["identities"]] == ["google"]


def test_notification_unknown_sub_and_bad_audience(client: TestClient, id_token: IdToken) -> None:
    payload = id_token("apple", "x", "n", events={"type": "consent-revoked", "sub": "nobody"})
    assert client.post("/api/auth/apple/notifications", json={"payload": payload}).status_code == 204
    bad = id_token("apple", "x", "n", aud="evil", events={"type": "consent-revoked", "sub": "nobody"})
    assert client.post("/api/auth/apple/notifications", json={"payload": bad}).status_code == 401


def test_bearer_logout_invalidates_token(client: TestClient, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    token = client.post(
        "/api/auth/google/native", json={"id_token": id_token("google", "alice", nonce), "nonce": nonce}
    ).json()["session_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/auth/logout", headers=bearer).status_code == 204
    assert client.get("/api/me", headers=bearer).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Basic xyz"}).status_code == 401


def test_https_public_url_uses_host_cookie(settings: Settings) -> None:
    from pydantic import HttpUrl

    from linguini.app import create_app

    settings.public_url = HttpUrl("https://linguini.example")
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        response = login_google(client, "alice")
    assert response.headers["set-cookie"].startswith("__Host-sid=")
    assert "Secure" in response.headers["set-cookie"]


def test_link_requires_the_same_signed_in_user(client: TestClient) -> None:
    login_google(client, "alice")
    state, nonce = start_login(client, "apple")
    client.post("/api/auth/logout", headers=CSRF_HEADERS)
    form = {"state": state, "code": fake_code("apple", "apple-alice", nonce)}
    client.post("/api/auth/apple/callback", data=form, follow_redirects=False)
    response = client.get(f"/api/auth/apple/finish?state={state}", follow_redirects=False)
    assert response.status_code == 400
