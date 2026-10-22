import pytest
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, login_google

pytestmark = pytest.mark.usefixtures("providers")


@pytest.fixture
def home(client: TestClient) -> str:
    login_google(client, "alice")
    return client.post("/api/households", json={"name": "Home"}, headers=CSRF_HEADERS).json()["id"]


def add(client: TestClient, home: str, name: str, quantity: float, unit: str, **extra: object) -> dict:
    body = {"name": name, "quantity": quantity, "unit": unit, **extra}
    response = client.post(f"/api/households/{home}/items", json=body, headers=CSRF_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def test_add_merges_by_normalized_name_and_converts_units(client: TestClient, home: str) -> None:
    first = add(client, home, "Rizs", 1, "kg")
    second = add(client, home, "rizs ", 50, "dkg")
    assert second["id"] == first["id"]
    assert second["quantity"] == pytest.approx(1.5)
    assert second["unit"] == "kg"
    assert second["last_purchased_at"] is not None


def test_dimension_mismatch_is_rejected(client: TestClient, home: str) -> None:
    add(client, home, "Sárgarépa", 6, "db")
    response = client.post(
        f"/api/households/{home}/items", json={"name": "sargarepa", "quantity": 500, "unit": "g"}, headers=CSRF_HEADERS
    )
    assert response.status_code == 409
    assert "tracked in pcs" in response.json()["detail"]


def test_unknown_unit_is_422(client: TestClient, home: str) -> None:
    response = client.post(
        f"/api/households/{home}/items", json={"name": "x", "quantity": 1, "unit": "bucket"}, headers=CSRF_HEADERS
    )
    assert response.status_code == 422


def test_search_folds_diacritics_and_prefixes(client: TestClient, home: str) -> None:
    add(client, home, "Tejföl", 2, "db")
    add(client, home, "Tej", 1, "l")
    add(client, home, "Kenyér", 1, "db")
    names = [i["name"] for i in client.get(f"/api/households/{home}/items", params={"q": "tejfol"}).json()]
    assert names == ["Tejföl"]
    names = [i["name"] for i in client.get(f"/api/households/{home}/items", params={"q": "tej"}).json()]
    assert set(names) == {"Tej", "Tejföl"}
    assert client.get(f"/api/households/{home}/items", params={"q": "zzz"}).json() == []


def test_patch_sets_absolute_quantity_and_unit(client: TestClient, home: str) -> None:
    item = add(client, home, "Liszt", 1, "kg")
    patched = client.patch(
        f"/api/households/{home}/items/{item['id']}", json={"quantity": 3, "unit": "db"}, headers=CSRF_HEADERS
    ).json()
    assert (patched["quantity"], patched["unit"], patched["dimension"]) == (3, "pcs", "count")
    events = client.get(f"/api/households/{home}/events").json()
    assert events[0]["quantity_before"] == 0
    assert events[0]["quantity_after"] == 3


def test_undo_reverts_and_is_single_use(client: TestClient, home: str) -> None:
    add(client, home, "Rizs", 1, "kg")
    add(client, home, "Rizs", 1, "kg")
    event = client.get(f"/api/households/{home}/events").json()[0]
    undo = client.post(f"/api/households/{home}/events/{event['id']}/undo", headers=CSRF_HEADERS)
    assert undo.status_code == 200
    assert undo.json()["cause"] == "undo"
    item = client.get(f"/api/households/{home}/items").json()[0]
    assert item["quantity"] == 1
    assert client.post(f"/api/households/{home}/events/{event['id']}/undo", headers=CSRF_HEADERS).status_code == 409
    assert (
        client.post(f"/api/households/{home}/events/{undo.json()['id']}/undo", headers=CSRF_HEADERS).status_code == 409
    )


def test_delete_item_removes_history(client: TestClient, home: str) -> None:
    item = add(client, home, "Rizs", 1, "kg")
    assert client.delete(f"/api/households/{home}/items/{item['id']}", headers=CSRF_HEADERS).status_code == 204
    assert client.get(f"/api/households/{home}/items").json() == []
    assert client.get(f"/api/households/{home}/events").json() == []


def test_other_household_cannot_see_items(client: TestClient, home: str) -> None:
    add(client, home, "Rizs", 1, "kg")
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    assert client.get(f"/api/households/{other}/items").json() == []
    ghost = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/households/{ghost}/items").status_code == 404


@pytest.mark.parametrize("query", ['a"b', '"', "NEAR(", "tej OR rizs", "rizs:", "*", "   "])
def test_search_survives_fts_syntax(client: TestClient, home: str, query: str) -> None:
    add(client, home, "Rizs", 1, "kg")
    response = client.get(f"/api/households/{home}/items", params={"q": query})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_search_matches_accented_query_against_plain_name(client: TestClient, home: str) -> None:
    add(client, home, "tejfol", 1, "db")
    add(client, home, "Barna rizs", 1, "kg")
    assert [i["name"] for i in client.get(f"/api/households/{home}/items", params={"q": "TEJFÖL"}).json()] == ["tejfol"]
    names = [i["name"] for i in client.get(f"/api/households/{home}/items", params={"q": "barna riz"}).json()]
    assert names == ["Barna rizs"]


def test_undo_across_dimension_change_is_refused(client: TestClient, home: str) -> None:
    item = add(client, home, "Rizs", 1, "kg")
    add_event = client.get(f"/api/households/{home}/events").json()[0]
    client.patch(f"/api/households/{home}/items/{item['id']}", json={"quantity": 3, "unit": "db"}, headers=CSRF_HEADERS)
    events = client.get(f"/api/households/{home}/events").json()
    assert [(e["dimension"], e["quantity_before"], e["quantity_after"]) for e in events] == [
        ("count", 0, 3),
        ("mass", 1000, 0),
        ("mass", 0, 1000),
    ]
    assert client.post(f"/api/households/{home}/events/{add_event['id']}/undo", headers=CSRF_HEADERS).status_code == 409
    set_event = events[0]
    undo = client.post(f"/api/households/{home}/events/{set_event['id']}/undo", headers=CSRF_HEADERS)
    assert undo.status_code == 200
    got = client.get(f"/api/households/{home}/items").json()[0]
    assert (got["quantity"], got["unit"]) == (0, "pcs")


def test_undo_of_positive_delta_clamps_at_zero(client: TestClient, home: str) -> None:
    item = add(client, home, "Alma", 5, "db")
    add_event = client.get(f"/api/households/{home}/events").json()[0]
    client.patch(f"/api/households/{home}/items/{item['id']}", json={"quantity": 1}, headers=CSRF_HEADERS)
    undo = client.post(f"/api/households/{home}/events/{add_event['id']}/undo", headers=CSRF_HEADERS).json()
    assert undo["quantity_after"] == 0


def test_patch_unit_only_dimension_change_is_422(client: TestClient, home: str) -> None:
    item = add(client, home, "Liszt", 500, "g")
    response = client.patch(f"/api/households/{home}/items/{item['id']}", json={"unit": "l"}, headers=CSRF_HEADERS)
    assert response.status_code == 422
    same = client.patch(f"/api/households/{home}/items/{item['id']}", json={"unit": "kg"}, headers=CSRF_HEADERS).json()
    assert (same["quantity"], same["unit"]) == (pytest.approx(0.5), "kg")


def test_patch_metadata_set_and_clear(client: TestClient, home: str) -> None:
    item = add(client, home, "Tej", 1, "l")
    url = f"/api/households/{home}/items/{item['id']}"
    patched = client.patch(
        url, json={"notes": "bio", "expires_at": "2026-11-01T00:00:00Z"}, headers=CSRF_HEADERS
    ).json()
    assert patched["notes"] == "bio" and patched["expires_at"].startswith("2026-11-01")
    cleared = client.patch(url, json={"notes": None, "expires_at": None}, headers=CSRF_HEADERS).json()
    assert cleared["notes"] is None and cleared["expires_at"] is None
    assert client.get(f"/api/households/{home}/events").json()[0]["cause"] == "manual"
    assert len(client.get(f"/api/households/{home}/events").json()) == 1
    zero = client.patch(url, json={"quantity": 0}, headers=CSRF_HEADERS)
    assert zero.status_code == 200 and zero.json()["quantity"] == 0
    assert client.patch(url, json={"quantity": -1}, headers=CSRF_HEADERS).status_code == 422


def test_isolation_for_patch_delete_undo_and_search(client: TestClient, home: str) -> None:
    item = add(client, home, "Rizs", 1, "kg")
    event = client.get(f"/api/households/{home}/events").json()[0]
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    add(client, other, "Rizs", 2, "kg")
    assert (
        client.patch(
            f"/api/households/{other}/items/{item['id']}", json={"quantity": 9}, headers=CSRF_HEADERS
        ).status_code
        == 404
    )
    assert client.delete(f"/api/households/{other}/items/{item['id']}", headers=CSRF_HEADERS).status_code == 404
    assert client.post(f"/api/households/{other}/events/{event['id']}/undo", headers=CSRF_HEADERS).status_code == 404
    found = client.get(f"/api/households/{other}/items", params={"q": "rizs"}).json()
    assert [i["quantity"] for i in found] == [2]
    bob = TestClient(client.app)
    invite = client.post(f"/api/households/{other}/invites", headers=CSRF_HEADERS).json()
    login_google(bob, "bob", invite=invite["code"])
    assert bob.get(f"/api/households/{home}/items").status_code == 404


def test_undo_last_turn_route_with_no_runs_is_empty(client: TestClient, home: str) -> None:
    add(client, home, "Rizs", 1, "kg")
    thread = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        f"/api/households/{home}/events/undo-last-turn", params={"thread_id": thread}, headers=CSRF_HEADERS
    )
    assert response.status_code == 200 and response.json() == []
