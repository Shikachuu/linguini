import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import uvicorn
from chat_models import Scripted
from flows import create_household, sign_in
from idp import FakeIdp, start_idp
from playwright.sync_api import BrowserContext, Page, Route, ViewportSize
from pydantic import HttpUrl
from pydantic_ai.models.test import TestModel
from pytest_playwright.pytest_playwright import CreateContextCallback

from linguini.app import create_app
from linguini.auth import apple, google
from linguini.config import Settings

DIST = Path(__file__).parents[2] / "web" / "dist"

type OpenPage = Callable[..., Page]

PHONE: ViewportSize = {"width": 390, "height": 844}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def idp_server() -> Iterator[FakeIdp]:
    server = start_idp()
    yield server
    server.shutdown()


@pytest.fixture
def idp(idp_server: FakeIdp, monkeypatch: pytest.MonkeyPatch) -> FakeIdp:
    monkeypatch.setattr(google, "AUTHORIZE_URL", f"{idp_server.cross_site_origin}/google")
    monkeypatch.setattr(apple, "AUTHORIZE_URL", f"{idp_server.cross_site_origin}/apple")
    return idp_server


@pytest.fixture
def scripted() -> Scripted:
    return Scripted()


@pytest.fixture
def server_url(settings: Settings, scripted: Scripted, providers: object, idp: FakeIdp) -> Iterator[str]:
    if not (DIST / "index.html").is_file():
        pytest.fail(f"{DIST} has no build; run `mise run build` first")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    app = create_app(
        settings.model_copy(update={"public_url": HttpUrl(url), "static_dir": DIST}),
        model=scripted.model(),
        summary_model=TestModel(custom_output_text="SUMMARY"),
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.05)
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def guard(server_url: str, idp: FakeIdp) -> Iterator[Callable[[BrowserContext], BrowserContext]]:
    errors: list[str] = []

    def local_only(route: Route) -> None:
        if route.request.url.startswith((server_url, idp.cross_site_origin)):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def apply(context: BrowserContext) -> BrowserContext:
        context.route("**/*", local_only)
        context.on("weberror", lambda error: errors.append(str(error.error)))
        return context

    yield apply
    assert errors == []


@pytest.fixture(autouse=True)
def guard_default_context(context: BrowserContext, guard: Callable[[BrowserContext], BrowserContext]) -> None:
    guard(context)


@pytest.fixture
def open_page(new_context: CreateContextCallback, guard: Callable[[BrowserContext], BrowserContext]) -> OpenPage:
    def open_(*, phone: bool = False) -> Page:
        context = new_context(viewport=PHONE, is_mobile=True, has_touch=True) if phone else new_context()
        return guard(context).new_page()

    return open_


@pytest.fixture
def home(page: Page, server_url: str, idp: FakeIdp) -> str:
    sign_in(page, server_url, idp)
    return create_household(page)
