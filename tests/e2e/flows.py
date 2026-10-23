import re

from idp import FakeIdp, Identity
from playwright.sync_api import Locator, Page, expect

HOUSEHOLD_CHAT = re.compile(r"/h/([^/]+)/chat$")


def sign_in(
    page: Page, server_url: str, idp: FakeIdp, who: Identity | None = None, *, path: str = "/", provider: str = "Google"
) -> None:
    idp.identity = who or Identity()
    page.goto(server_url + path)
    page.get_by_role("link", name=f"Continue with {provider}").click()


def create_household(page: Page, name: str = "Home") -> str:
    expect(page.get_by_text("Create a household")).to_be_visible()
    page.get_by_label("Name").fill(name)
    page.get_by_role("button", name="Create").click()
    expect(page).to_have_url(HOUSEHOLD_CHAT)
    match = HOUSEHOLD_CHAT.search(page.url)
    assert match
    return match.group(1)


def send(page: Page, text: str) -> None:
    box = page.get_by_placeholder("Message the kitchen")
    box.fill(text)
    box.press("Enter")


def pantry_row(page: Page, name: str) -> Locator:
    return page.get_by_role("listitem").filter(has=page.get_by_text(name, exact=True))
