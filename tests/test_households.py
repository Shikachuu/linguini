import pytest
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, login_google

pytestmark = pytest.mark.usefixtures("providers")


@pytest.fixture
def alice(client: TestClient) -> TestClient:
    login_google(client, "alice")
    return client


def test_create_list_rename_delete(alice: TestClient) -> None:
    created = alice.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    assert [h["name"] for h in alice.get("/api/households").json()] == ["Home"]
    renamed = alice.patch(f"/api/households/{created['id']}", json={"name": "Flat"}, headers=CSRF_HEADERS).json()
    assert renamed["name"] == "Flat"
    assert alice.delete(f"/api/households/{created['id']}", headers=CSRF_HEADERS).status_code == 204
    assert alice.get("/api/households").json() == []


def test_non_member_gets_404(alice: TestClient) -> None:
    created = alice.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    invite = alice.post(f"/api/households/{created['id']}/invites", headers=CSRF_HEADERS).json()
    bob = TestClient(alice.app)
    login_google(bob, "bob", invite=invite["code"])
    other = bob.post("/api/households", json={"name": "Bob's"}, headers=CSRF_HEADERS).json()
    assert alice.get(f"/api/households/{other['id']}").status_code == 404
    assert alice.get(f"/api/households/{other['id']}/members").status_code == 404


def test_members_and_removal(alice: TestClient) -> None:
    created = alice.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    invite = alice.post(f"/api/households/{created['id']}/invites", headers=CSRF_HEADERS).json()
    bob = TestClient(alice.app)
    login_google(bob, "bob", invite=invite["code"])
    members = alice.get(f"/api/households/{created['id']}/members").json()
    assert [m["display_name"] for m in members] == ["Alice", "Bob"]

    bob_id = bob.get("/api/me").json()["id"]
    assert alice.delete(f"/api/households/{created['id']}/members/{bob_id}", headers=CSRF_HEADERS).status_code == 204
    assert bob.get(f"/api/households/{created['id']}").status_code == 404

    alice_id = alice.get("/api/me").json()["id"]
    alice.delete(f"/api/households/{created['id']}/members/{alice_id}", headers=CSRF_HEADERS)
    assert alice.get("/api/households").json() == []


def test_accept_invite_while_signed_in(alice: TestClient) -> None:
    created = alice.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    signup_invite = alice.post(f"/api/households/{created['id']}/invites", headers=CSRF_HEADERS).json()
    second_invite = alice.post(f"/api/households/{created['id']}/invites", headers=CSRF_HEADERS).json()
    bob = TestClient(alice.app)
    login_google(bob, "bob", invite=signup_invite["code"])
    joined = bob.post(f"/api/invites/{second_invite['code']}/accept", headers=CSRF_HEADERS)
    assert joined.status_code == 200
    assert bob.post(f"/api/invites/{second_invite['code']}/accept", headers=CSRF_HEADERS).status_code == 404
    assert len(alice.get(f"/api/households/{created['id']}/members").json()) == 2


def test_name_validation_and_removing_non_member(alice: TestClient) -> None:
    assert alice.post("/api/households", json={"name": ""}, headers=CSRF_HEADERS).status_code == 422
    assert alice.post("/api/households", json={"name": "x" * 81}, headers=CSRF_HEADERS).status_code == 422
    created = alice.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()
    ghost = "00000000-0000-0000-0000-000000000000"
    assert alice.delete(f"/api/households/{created['id']}/members/{ghost}", headers=CSRF_HEADERS).status_code == 404
