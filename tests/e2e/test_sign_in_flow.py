import re

from conftest import OpenPage
from flows import create_household, sign_in
from idp import FakeIdp, Identity
from playwright.sync_api import Page, expect


def test_google_sign_in_then_create_household(page: Page, server_url: str, idp: FakeIdp) -> None:
    page.goto(server_url + "/")
    expect(page).to_have_url(re.compile(r"/login$"))
    expect(page.get_by_role("link", name="Continue with Apple")).to_be_visible()
    sign_in(page, server_url, idp)
    create_household(page, "Cabin")
    expect(page.get_by_role("button", name="Cabin").first).to_be_visible()


def test_provider_error_is_shown_on_login(page: Page, server_url: str, idp: FakeIdp) -> None:
    sign_in(page, server_url, idp, Identity(error="access_denied"))
    expect(page).to_have_url(re.compile(r"/login\?login_error=access_denied$"))
    expect(page.get_by_role("alert")).to_have_text("Sign-in was cancelled.")


def test_uninvited_newcomer_is_turned_away(
    page: Page, home: str, server_url: str, idp: FakeIdp, open_page: OpenPage
) -> None:
    stranger = open_page()
    sign_in(stranger, server_url, idp, Identity("mallory", "Mallory"))
    expect(stranger).to_have_url(re.compile(r"/login\?login_error=invite_required$"))
    expect(stranger.get_by_role("alert")).to_have_text(
        "You need an invite link from a household member to create an account."
    )


def test_deep_link_survives_sign_in(page: Page, server_url: str, idp: FakeIdp) -> None:
    sign_in(page, server_url, idp)
    hid = create_household(page)
    page.context.clear_cookies()
    sign_in(page, server_url, idp, path=f"/h/{hid}/recipes")
    expect(page).to_have_url(f"{server_url}/h/{hid}/recipes")
    expect(page.get_by_role("heading", name="Recipes")).to_be_visible()


def test_apple_form_post_sign_in(page: Page, server_url: str, idp: FakeIdp) -> None:
    sign_in(page, server_url, idp, Identity("bob", "Bob Test"), provider="Apple")
    create_household(page)
    page.goto(server_url + "/account")
    expect(page.get_by_role("main").get_by_text("Bob Test")).to_be_visible()
    expect(page.get_by_text("bob@privaterelay.appleid.com")).to_be_visible()


def test_invite_link_adds_a_second_member(page: Page, server_url: str, idp: FakeIdp, open_page: OpenPage) -> None:
    sign_in(page, server_url, idp)
    hid = create_household(page)
    page.goto(f"{server_url}/h/{hid}/settings")
    page.get_by_role("button", name="Create invite link").click()
    link = page.get_by_role("textbox", name="Invite link").input_value()
    assert link.startswith(f"{server_url}/invite/")

    guest = open_page()
    sign_in(guest, server_url, idp, Identity("carol", "Carol"), path=link.removeprefix(server_url))
    expect(guest).to_have_url(f"{server_url}/h/{hid}/chat")

    page.reload()
    expect(page.get_by_text("Carol")).to_be_visible()


def test_unknown_invite_is_explained(page: Page, home: str, server_url: str) -> None:
    page.goto(server_url + "/invite/not-a-real-code")
    expect(page.get_by_text(re.compile(r"^This invite could not be used: "))).to_be_visible()
    page.get_by_role("link", name="Go home").click()
    expect(page).to_have_url(f"{server_url}/h/{home}/chat")


def test_members_cannot_open_other_households(
    page: Page, home: str, server_url: str, idp: FakeIdp, open_page: OpenPage
) -> None:
    page.goto(server_url + "/welcome")
    shared = create_household(page, "Shared")
    page.goto(f"{server_url}/h/{shared}/settings")
    page.get_by_role("button", name="Create invite link").click()
    link = page.get_by_role("textbox", name="Invite link").input_value()

    guest = open_page()
    sign_in(guest, server_url, idp, Identity("carol", "Carol"), path=link.removeprefix(server_url))
    expect(guest).to_have_url(f"{server_url}/h/{shared}/chat")
    guest.goto(f"{server_url}/h/{home}/inventory")
    expect(guest).to_have_url(f"{server_url}/h/{shared}/chat")
    guest.get_by_role("button", name="Shared").first.click()
    expect(guest.get_by_role("menuitem", name="Home")).to_have_count(0)


def test_delete_account_signs_out(page: Page, home: str, server_url: str) -> None:
    page.goto(server_url + "/account")
    page.get_by_role("button", name="Delete account").click()
    confirm = page.get_by_role("alertdialog")
    expect(confirm.get_by_role("button", name="Delete account")).to_be_disabled()
    confirm.get_by_label("Type delete my account to confirm").fill("delete my account")
    confirm.get_by_role("button", name="Delete account").click()
    expect(page).to_have_url(re.compile(r"/login"))
    page.goto(f"{server_url}/h/{home}/chat")
    expect(page).to_have_url(re.compile(r"/login"))
