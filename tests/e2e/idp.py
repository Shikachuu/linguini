import json
import threading
from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from helpers import fake_code


@dataclass
class Identity:
    sub: str = "alice"
    name: str = "Alice"
    error: str | None = None


class FakeIdp(ThreadingHTTPServer):
    identity: Identity

    @property
    def cross_site_origin(self) -> str:
        return f"http://localhost:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        assert isinstance(self.server, FakeIdp)
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        who = self.server.identity
        provider = parts.path.strip("/")
        result = {"state": query["state"]}
        if who.error:
            result["error"] = who.error
        else:
            result["code"] = fake_code(provider, who.sub, query["nonce"])
        if provider == "google":
            self.send_response(303)
            self.send_header("location", f"{query['redirect_uri']}?{urlencode(result)}")
            self.end_headers()
            return
        first, _, last = who.name.partition(" ")
        result["user"] = json.dumps({"name": {"firstName": first, "lastName": last}})
        inputs = "".join(f'<input type="hidden" name="{k}" value="{escape(v)}">' for k, v in result.items())
        body = (
            f'<form method="post" action="{escape(query["redirect_uri"])}">{inputs}</form>'
            "<script>document.forms[0].submit()</script>"
        )
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


def start_idp() -> FakeIdp:
    server = FakeIdp(("127.0.0.1", 0), _Handler)
    server.identity = Identity()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
