import pytest
import respx
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, IdToken, fake_code, login_apple, login_google, start_login

from linguini.auth import google

pytestmark = pytest.mark.usefixtures("providers")


def test_first_google_login_creates_account_and_cookie(client: TestClient) -> None:
    response = login_google(client, "alice")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "sid=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    me = client.get("/api/me").json()
    assert me["display_name"] == "Alice"
    assert me["identities"] == [{"provider": "google", "email": "alice@gmail.com"}]


def test_second_user_needs_invite(client: TestClient) -> None:
    login_google(client, "alice")
    stranger = TestClient(client.app)
    response = login_google(stranger, "bob")
    assert response.status_code == 403
    assert response.json()["detail"] == "invite_required"


def test_invite_lets_second_user_in_and_joins_household(client: TestClient) -> None:
    login_google(client, "alice")
    household = client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    invite = client.post(f"/api/households/{household['id']}/invites", headers=CSRF_HEADERS).json()
    assert invite["url"].endswith(f"/invite/{invite['code']}")

    bob = TestClient(client.app)
    assert login_google(bob, "bob", invite=invite["code"]).status_code == 303
    assert [h["name"] for h in bob.get("/api/me").json()["households"]] == ["Home"]

    carol = TestClient(client.app)
    assert login_google(carol, "carol", invite=invite["code"]).status_code == 403


def test_existing_user_logs_in_again(client: TestClient) -> None:
    login_google(client, "alice")
    first = client.get("/api/me").json()["id"]
    client.post("/api/auth/logout", headers=CSRF_HEADERS)
    assert client.get("/api/me").status_code == 401
    login_google(client, "alice")
    assert client.get("/api/me").json()["id"] == first


def test_return_to_must_be_relative(client: TestClient) -> None:
    response = login_google(client, "alice", return_to="https://evil.example/")
    assert response.headers["location"] == "/"


def test_wrong_browser_cannot_finish(client: TestClient) -> None:
    state, nonce = start_login(client, "google")
    other = TestClient(client.app)
    response = other.get(
        "/api/auth/google/callback", params={"state": state, "code": fake_code("google", "alice", nonce)}
    )
    assert response.status_code == 400
    assert "different browser" in response.json()["detail"]


def test_nonce_mismatch_is_rejected(client: TestClient) -> None:
    state, _ = start_login(client, "google")
    response = client.get("/api/auth/google/callback", params={"state": state, "code": "google:alice:wrong"})
    assert response.status_code == 401


def test_state_is_single_use(client: TestClient) -> None:
    state, nonce = start_login(client, "google")
    params = {"state": state, "code": fake_code("google", "alice", nonce)}
    assert client.get("/api/auth/google/callback", params=params, follow_redirects=False).status_code == 303
    assert client.get("/api/auth/google/callback", params=params, follow_redirects=False).status_code == 400


def test_apple_form_post_login_keeps_one_time_name(client: TestClient) -> None:
    user_field = '{"name":{"firstName":"Ada","lastName":"Lovelace"},"email":"x@privaterelay.appleid.com"}'
    response = login_apple(client, "apple-ada", user_field)
    assert response.status_code == 303, response.text
    me = client.get("/api/me").json()
    assert me["display_name"] == "Ada Lovelace"
    assert me["identities"][0]["provider"] == "apple"


def test_apple_cancel_redirects_with_error(client: TestClient) -> None:
    state, _ = start_login(client, "apple")
    response = client.post(
        "/api/auth/apple/callback", data={"state": state, "error": "user_cancelled_authorize"}, follow_redirects=False
    )
    assert response.headers["location"] == "/?login_error=user_cancelled_authorize"


def test_link_second_provider_to_same_user(client: TestClient) -> None:
    login_google(client, "alice")
    user_id = client.get("/api/me").json()["id"]
    assert login_apple(client, "apple-alice").status_code == 303
    me = client.get("/api/me").json()
    assert me["id"] == user_id
    assert sorted(i["provider"] for i in me["identities"]) == ["apple", "google"]


def test_native_login_with_bearer(client: TestClient, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    token = id_token("google", "alice", nonce, aud="google-ios")
    response = client.post("/api/auth/google/native", json={"id_token": token, "nonce": nonce})
    assert response.status_code == 200, response.text
    bearer = {"Authorization": f"Bearer {response.json()['session_token']}"}
    assert client.get("/api/me", headers=bearer).json()["display_name"] == "Alice"
    created = client.post("/api/households", json={"name": "Phone"}, headers=bearer)
    assert created.status_code == 201


def test_native_nonce_is_single_use(client: TestClient, id_token: IdToken) -> None:
    nonce = client.post("/api/auth/nonce").json()["nonce"]
    body = {"id_token": id_token("google", "alice", nonce), "nonce": nonce}
    assert client.post("/api/auth/google/native", json=body).status_code == 200
    assert client.post("/api/auth/google/native", json=body).status_code == 400


def test_native_second_user_needs_invite(client: TestClient, id_token: IdToken) -> None:
    login_google(client, "alice")
    phone = TestClient(client.app)
    nonce = phone.post("/api/auth/nonce").json()["nonce"]
    body = {"id_token": id_token("google", "bob", nonce), "nonce": nonce}
    assert phone.post("/api/auth/google/native", json=body).status_code == 403


def test_csrf_blocks_cookie_posts_without_proof(client: TestClient) -> None:
    login_google(client, "alice")
    assert client.post("/api/households", json={"name": "X"}).status_code == 403
    bad_origin = {"X-Requested-With": "linguini", "Origin": "https://evil.example"}
    assert client.post("/api/households", json={"name": "X"}, headers=bad_origin).status_code == 403
    good_origin = {"X-Requested-With": "linguini", "Origin": "http://localhost:8000"}
    assert client.post("/api/households", json={"name": "X"}, headers=good_origin).status_code == 201


def test_apple_notification_deletes_identity_and_sessions(client: TestClient, id_token: IdToken) -> None:
    login_apple(client, "apple-ada")
    payload = id_token("apple", "irrelevant", "n", events={"type": "consent-revoked", "sub": "apple-ada"})
    response = client.post("/api/auth/apple/notifications", json={"payload": payload})
    assert response.status_code == 204
    assert client.get("/api/me").status_code == 401


def test_unconfigured_provider_is_404(settings) -> None:
    from linguini.app import create_app

    settings.google_client_id = None
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404


def test_unknown_provider_is_404(client: TestClient) -> None:
    assert client.get("/api/auth/github/start", follow_redirects=False).status_code == 404


def test_jwks_is_fetched_once(client: TestClient, providers: respx.MockRouter) -> None:
    login_google(client, "alice")
    client.post("/api/auth/logout", headers=CSRF_HEADERS)
    login_google(client, "alice")
    assert providers.get(google.JWKS_URL).call_count == 1
