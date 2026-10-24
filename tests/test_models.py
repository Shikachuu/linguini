import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from pydantic import HttpUrl, SecretStr
from pydantic_ai import Agent

from linguini.chat.agent import build_model, session_settings
from linguini.config import Settings


class _Completions(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, str]]] = []

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["content-length"]))
        self.seen.append({"path": self.path, **{k.lower(): v for k, v in self.headers.items()}})
        body = json.dumps(
            {
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-v4.1-flash",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def llm_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Completions)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Completions.seen.clear()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def test_no_session_header_by_default() -> None:
    assert session_settings(Settings(secret_key=SecretStr("x")), "t1") is None


@pytest.mark.anyio
async def test_session_header_is_sent_with_the_request(llm_url: str) -> None:
    settings = Settings(
        secret_key=SecretStr("x"),
        openai_base_url=HttpUrl(llm_url),
        openai_api_key=SecretStr("key"),
        model="deepseek-v4.1-flash",
        session_header="x-opencode-session",
    )
    result = await Agent(build_model(settings)).run("hello", model_settings=session_settings(settings, "thread-1"))
    assert result.output == "hi"
    [request] = _Completions.seen
    assert request["path"] == "/v1/chat/completions"
    assert request["x-opencode-session"] == "thread-1"
    assert request["authorization"] == "Bearer key"
