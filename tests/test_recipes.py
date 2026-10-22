import uuid
from collections.abc import Iterator

import pytest
from chat_models import Scripted
from fastapi.testclient import TestClient
from helpers import CSRF_HEADERS, chat, login_google
from pydantic_ai.models.test import TestModel

from linguini.app import create_app
from linguini.config import Settings

pytestmark = pytest.mark.usefixtures("providers")

BOLOGNESE = {
    "title": "Bolognese",
    "servings": 4,
    "ingredients": [
        {"name": "darált hús", "quantity": 500, "unit": "g"},
        {"name": "paradicsom", "quantity": 400, "unit": "g"},
        {"name": "parmezán", "quantity": 30, "unit": "g", "optional": True},
    ],
    "steps": ["Brown the meat.", " Simmer. ", ""],
    "allergens": ["Dairy", "dairy", " celery "],
}


@pytest.fixture
def scripted() -> Scripted:
    return Scripted()


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


def add(client: TestClient, home: str, name: str, quantity: float, unit: str) -> None:
    body = {"name": name, "quantity": quantity, "unit": unit}
    assert client.post(f"/api/households/{home}/items", json=body, headers=CSRF_HEADERS).status_code == 201


def quantities(client: TestClient, home: str) -> dict[str, tuple[float, str]]:
    return {i["name"]: (i["quantity"], i["unit"]) for i in client.get(f"/api/households/{home}/items").json()}


def save(client: TestClient, home: str, **overrides: object) -> dict:
    response = client.post(f"/api/households/{home}/recipes", json={**BOLOGNESE, **overrides}, headers=CSRF_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_normalizes(client: TestClient, home: str) -> None:
    recipe = save(client, home, ingredients=[{"name": "alma", "quantity": 2, "unit": "db"}])
    assert recipe["allergens"] == ["celery", "dairy"]
    assert recipe["steps"] == ["Brown the meat.", "Simmer."]
    assert recipe["source"] == "manual"
    assert recipe["ingredients"][0]["unit"] == "pcs"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("bolog", ["Bolognese"]),
        ("RIZOTTÓ", ["Rizotto"]),
        ("rizotto", ["Rizotto"]),
        ("daralt", ["Bolognese"]),
        ("x", []),
    ],
)
def test_search_by_title_or_ingredient_ignores_accents(
    client: TestClient, home: str, query: str, expected: list
) -> None:
    save(client, home)
    save(client, home, title="Rizotto", ingredients=[{"name": "rizs", "quantity": 200, "unit": "g"}])
    found = client.get(f"/api/households/{home}/recipes", params={"q": query}).json()
    assert [r["title"] for r in found] == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"ingredients": [{"name": "x", "quantity": 1, "unit": "bucket"}]},
        {"ingredients": []},
        {"ingredients": [{"name": "x", "quantity": 0, "unit": "g"}]},
        {"servings": 0},
        {"servings": 101},
        {"title": ""},
    ],
)
def test_validation_rejects(client: TestClient, home: str, overrides: dict) -> None:
    body = {**BOLOGNESE, **overrides}
    assert client.post(f"/api/households/{home}/recipes", json=body, headers=CSRF_HEADERS).status_code == 422


def test_servings_bounds_accepted(client: TestClient, home: str) -> None:
    assert save(client, home, servings=1)["servings"] == 1
    assert save(client, home, servings=100)["servings"] == 100


def test_replace_keeps_source_and_renormalizes(client: TestClient, home: str) -> None:
    recipe = save(client, home)
    url = f"/api/households/{home}/recipes/{recipe['id']}"
    body = {**BOLOGNESE, "title": "Ragu", "servings": 6, "allergens": ["Egg", "egg"]}
    replaced = client.put(url, json=body, headers=CSRF_HEADERS).json()
    assert (replaced["title"], replaced["servings"], replaced["allergens"]) == ("Ragu", 6, ["egg"])
    assert replaced["source"] == "manual" and replaced["updated_at"] > recipe["updated_at"]
    ghost = f"/api/households/{home}/recipes/{uuid.uuid7()}"
    assert client.put(ghost, json=BOLOGNESE, headers=CSRF_HEADERS).status_code == 404


def test_delete(client: TestClient, home: str) -> None:
    recipe = save(client, home)
    url = f"/api/households/{home}/recipes/{recipe['id']}"
    assert client.delete(url, headers=CSRF_HEADERS).status_code == 204
    assert client.get(url).status_code == 404


def test_isolation_across_households_and_users(client: TestClient, home: str) -> None:
    recipe = save(client, home)
    other = client.post("/api/households", json={"name": "Other"}, headers=CSRF_HEADERS).json()["id"]
    foreign = f"/api/households/{other}/recipes/{recipe['id']}"
    assert client.get(foreign).status_code == 404
    assert client.put(foreign, json=BOLOGNESE, headers=CSRF_HEADERS).status_code == 404
    assert client.delete(foreign, headers=CSRF_HEADERS).status_code == 404
    assert client.post(f"{foreign}/cook", json={}, headers=CSRF_HEADERS).status_code == 404
    assert client.get(f"/api/households/{other}/recipes").json() == []
    bob = TestClient(client.app)
    invite = client.post(f"/api/households/{other}/invites", headers=CSRF_HEADERS).json()
    login_google(bob, "bob", invite=invite["code"])
    assert bob.get(f"/api/households/{home}/recipes").status_code == 404
    assert (
        bob.post(f"/api/households/{home}/recipes/{recipe['id']}/cook", json={}, headers=CSRF_HEADERS).status_code
        == 404
    )


def test_cook_scales_skips_optional_and_reports_missing(client: TestClient, home: str) -> None:
    recipe = save(client, home)
    add(client, home, "darált hús", 1, "kg")
    add(client, home, "parmezán", 100, "g")
    cooked = client.post(
        f"/api/households/{home}/recipes/{recipe['id']}/cook", json={"servings": 2}, headers=CSRF_HEADERS
    )
    assert cooked.status_code == 200, cooked.text
    results = {r["name"]: r for r in cooked.json()["results"]}
    assert set(results) == {"darált hús", "paradicsom"}
    assert results["darált hús"]["ok"] and results["darált hús"]["event_id"]
    assert not results["paradicsom"]["ok"] and "not in the inventory" in results["paradicsom"]["message"]
    got = quantities(client, home)
    assert got["darált hús"] == (pytest.approx(0.75), "kg") and got["parmezán"] == (100, "g")
    assert client.get(f"/api/households/{home}/events").json()[0]["cause"] == "cook"


def test_cook_shortfall_default_servings_and_undo(client: TestClient, home: str) -> None:
    recipe = save(client, home)
    add(client, home, "darált hús", 300, "g")
    add(client, home, "paradicsom", 1, "kg")
    cooked = client.post(f"/api/households/{home}/recipes/{recipe['id']}/cook", headers=CSRF_HEADERS).json()
    meat = next(r for r in cooked["results"] if r["name"] == "darált hús")
    assert meat["ok"] and "short by 200 g" in meat["message"]
    got = quantities(client, home)
    assert got["darált hús"] == (0, "g") and got["paradicsom"] == (pytest.approx(0.6), "kg")
    undo = client.post(f"/api/households/{home}/events/{meat['event_id']}/undo", headers=CSRF_HEADERS)
    assert undo.status_code == 200
    assert quantities(client, home)["darált hús"] == (300, "g")


def test_cook_fractional_and_upscaled_servings(client: TestClient, home: str) -> None:
    recipe = save(client, home)
    add(client, home, "darált hús", 2, "kg")
    add(client, home, "paradicsom", 2, "kg")
    client.post(f"/api/households/{home}/recipes/{recipe['id']}/cook", json={"servings": 3}, headers=CSRF_HEADERS)
    assert quantities(client, home)["darált hús"] == (pytest.approx(1.625), "kg")
    client.post(f"/api/households/{home}/recipes/{recipe['id']}/cook", json={"servings": 8}, headers=CSRF_HEADERS)
    assert quantities(client, home)["darált hús"] == (pytest.approx(0.625), "kg")
    bad = client.post(f"/api/households/{home}/recipes/{recipe['id']}/cook", json={"servings": 0}, headers=CSRF_HEADERS)
    assert bad.status_code == 422


def test_agent_saves_cooks_and_undoes(client: TestClient, home: str, thread: str, scripted: Scripted) -> None:
    add(client, home, "rizs", 1, "kg")
    chat(client, home, thread, "save Rizottó")
    saved = client.get(f"/api/households/{home}/recipes").json()
    assert [(r["title"], r["source"], r["allergens"]) for r in saved] == [("Rizottó", "chat", ["dairy"])]
    assert "Done:" in chat(client, home, thread, "cook rizott")
    got = quantities(client, home)
    assert got["rizs"] == (pytest.approx(0.6), "kg") and "vaj" not in got
    assert client.get(f"/api/households/{home}/events").json()[0]["cause"] == "cook"
    chat(client, home, thread, "undo")
    assert quantities(client, home)["rizs"] == (1, "kg")
    chat(client, home, thread, "cook nothing-saved")
    assert quantities(client, home)["rizs"] == (1, "kg")
    assert len(client.get(f"/api/households/{home}/events").json()) == 3


def test_agent_recipe_tool_retries(client: TestClient, home: str, thread: str, scripted: Scripted) -> None:
    add(client, home, "rizs", 1, "kg")
    chat(client, home, thread, "cook id garbage")
    assert "recipe_id must be" in scripted.retries[-1]
    chat(client, home, thread, f"cook id {uuid.uuid7()}")
    assert "Recipe not found" in scripted.retries[-1]
    chat(client, home, thread, f"recipe {uuid.uuid7()}")
    assert "Recipe not found" in scripted.retries[-1]
    recipe = save(client, home, ingredients=[{"name": "rizs", "quantity": 100, "unit": "g"}])
    chat(client, home, thread, f"cook big {recipe['id']}")
    assert "servings must be between" in scripted.retries[-1]
    assert quantities(client, home)["rizs"] == (1, "kg")
    assert client.get(f"/api/households/{home}/events").json()[0]["cause"] == "manual"
    assert chat(client, home, thread, f"recipe {recipe['id']}").count("Bolognese") >= 1
