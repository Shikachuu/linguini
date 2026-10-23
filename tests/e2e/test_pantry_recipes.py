import re

from flows import pantry_row
from playwright.sync_api import Locator, Page, expect


def fill_item(page: Page, name: str, amount: str, unit: str) -> Locator:
    page.get_by_role("button", name="Add").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill(name)
    dialog.get_by_label("Amount to add").fill(amount)
    dialog.get_by_label("Unit").fill(unit)
    dialog.get_by_role("button", name="Add").click()
    return dialog


def add_item(page: Page, name: str, amount: str, unit: str) -> None:
    expect(fill_item(page, name, amount, unit)).to_be_hidden()


def test_pantry_add_edit_and_history(page: Page, home: str, server_url: str) -> None:
    page.goto(f"{server_url}/h/{home}/inventory")
    expect(page.get_by_text("The pantry is empty")).to_be_visible()
    add_item(page, "tej", "2", "l")
    expect(pantry_row(page, "tej").get_by_text("2 l", exact=True)).to_be_visible()

    page.get_by_role("button", name="Edit tej").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Quantity").fill("1.5")
    dialog.get_by_role("button", name="Save").click()
    expect(pantry_row(page, "tej").get_by_text("1.5 l", exact=True)).to_be_visible()

    page.get_by_role("link", name="History").click()
    expect(page.get_by_text("2,000 ml -> 1,500 ml")).to_be_visible()
    expect(page.get_by_text("0 ml -> 2,000 ml")).to_be_visible()


def test_unit_conflict_is_explained(page: Page, home: str, server_url: str) -> None:
    page.goto(f"{server_url}/h/{home}/inventory")
    add_item(page, "liszt", "1", "kg")
    dialog = fill_item(page, "liszt", "2", "pcs")
    expect(dialog.get_by_role("alert")).to_contain_text("liszt is tracked in kg (mass); pcs is count")


def test_recipe_create_cook_and_undo(page: Page, home: str, server_url: str) -> None:
    page.goto(f"{server_url}/h/{home}/inventory")
    add_item(page, "tej", "2", "l")

    page.goto(f"{server_url}/h/{home}/recipes/new")
    page.get_by_label("Title").fill("Tejberizs")
    page.get_by_label("Ingredient 1 name").fill("tej")
    page.get_by_label("Ingredient 1 quantity").fill("500")
    page.get_by_label("Ingredient 1 unit").fill("ml")
    page.get_by_role("button", name="Ingredient", exact=True).click()
    page.get_by_label("Ingredient 2 name").fill("rizs")
    page.get_by_label("Ingredient 2 quantity").fill("100")
    page.get_by_label("Ingredient 2 unit").fill("g")
    page.get_by_label("Allergens, comma separated").fill("Dairy")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("heading", name="Tejberizs")).to_be_visible()
    expect(page.get_by_text("dairy", exact=True)).to_be_visible()

    page.get_by_role("button", name="Cook").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Cook").click()
    results = dialog.get_by_role("list", name="Cook results")
    expect(results.get_by_text(re.compile(r"^tej: 2 l -> 1\.5 l$"))).to_be_visible()
    expect(results.get_by_label("failed")).to_have_count(1)
    results.get_by_role("button", name="Undo").click()
    expect(results.get_by_text("Undone")).to_be_visible()

    page.goto(f"{server_url}/h/{home}/inventory")
    expect(pantry_row(page, "tej").get_by_text("2 l", exact=True)).to_be_visible()


def test_recipe_search(page: Page, home: str, server_url: str) -> None:
    for title in ["Gulyas", "Palacsinta"]:
        page.goto(f"{server_url}/h/{home}/recipes/new")
        page.get_by_label("Title").fill(title)
        page.get_by_label("Ingredient 1 name").fill("liszt")
        page.get_by_label("Ingredient 1 quantity").fill("100")
        page.get_by_role("button", name="Save").click()
        expect(page.get_by_role("heading", name=title)).to_be_visible()
    page.goto(f"{server_url}/h/{home}/recipes")
    page.get_by_placeholder("Search by title or ingredient").fill("pala")
    expect(page.get_by_role("link", name=re.compile(r"Palacsinta"))).to_be_visible()
    expect(page.get_by_role("link", name=re.compile(r"Gulyas"))).to_be_hidden()
