import re

from conftest import OpenPage
from flows import create_household, pantry_row, send, sign_in
from idp import FakeIdp
from playwright.sync_api import Page, expect


def open_new_chat(page: Page) -> None:
    page.get_by_role("button", name="New chat").first.click()
    expect(page).to_have_url(re.compile(r"/chat/[^/]+$"))


def test_tool_call_streams_and_can_be_undone(page: Page, home: str, server_url: str) -> None:
    open_new_chat(page)
    send(page, "add 1 kg rizs")
    changes = page.get_by_role("list", name="Added to the pantry")
    expect(changes.get_by_text("rizs: 0 kg -> 1 kg", exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile(r"^Done: "))).to_be_visible()
    expect(page.get_by_role("heading", level=2)).to_have_text("add 1 kg rizs")

    changes.get_by_role("button", name="Undo").click()
    expect(changes.get_by_text("Undone")).to_be_visible()
    page.goto(f"{server_url}/h/{home}/inventory")
    expect(pantry_row(page, "rizs").get_by_text("0 kg", exact=True)).to_be_visible()


def test_history_survives_reload(page: Page, home: str) -> None:
    open_new_chat(page)
    send(page, "hello")
    expect(page.get_by_text("echo: hello (history=0)")).to_be_visible()
    send(page, "add 2 pcs tojas")
    expect(page.get_by_text("tojas: 0 pcs -> 2 pcs", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_text("echo: hello (history=0)")).to_be_visible()
    expect(page.get_by_text("tojas: 0 pcs -> 2 pcs", exact=True)).to_be_visible()


def test_undo_last_turn(page: Page, home: str, server_url: str) -> None:
    open_new_chat(page)
    send(page, "add 3 pcs alma")
    expect(page.get_by_text("alma: 0 pcs -> 3 pcs", exact=True)).to_be_visible()
    page.get_by_role("button", name="Undo last turn").click()
    expect(page.get_by_text("Undid 1 pantry changes")).to_be_visible()
    page.goto(f"{server_url}/h/{home}/inventory")
    expect(pantry_row(page, "alma").get_by_text("0 pcs", exact=True)).to_be_visible()


def test_model_failure_keeps_the_chat_usable(page: Page, home: str) -> None:
    open_new_chat(page)
    send(page, "boom")
    expect(page.locator("[data-sonner-toast]")).to_be_visible()
    send(page, "hello again")
    expect(page.get_by_text(re.compile(r"^echo: hello again"))).to_be_visible()


def test_mobile_shows_one_pane_at_a_time(server_url: str, idp: FakeIdp, open_page: OpenPage) -> None:
    page = open_page(phone=True)
    sign_in(page, server_url, idp)
    create_household(page)
    expect(page.get_by_role("link", name="Pantry")).to_be_visible()
    open_new_chat(page)
    expect(page.get_by_role("heading", name="Chats")).to_be_hidden()
    send(page, "hello")
    expect(page.get_by_text("echo: hello (history=0)")).to_be_visible()
    page.get_by_role("link", name="Back to chats").click()
    expect(page.get_by_role("heading", name="Chats")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile(r"^hello"))).to_be_visible()


def test_desktop_shows_threads_beside_the_conversation(page: Page, home: str) -> None:
    open_new_chat(page)
    expect(page.get_by_role("heading", name="Chats")).to_be_visible()
    expect(page.get_by_placeholder("Message the kitchen")).to_be_visible()
