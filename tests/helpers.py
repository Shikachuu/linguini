import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from linguini.auth import apple, google

CSRF_HEADERS = {"X-Requested-With": "linguini", "Sec-Fetch-Site": "same-origin"}


class IdToken:
    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        self.key = key

    def __call__(self, provider: str, sub: str, nonce: str, **extra: Any) -> str:
        now = datetime.now(tz=UTC)
        claims: dict[str, Any]
        if provider == "google":
            claims = {"iss": google.ISSUERS[0], "aud": "google-web", "email": f"{sub}@gmail.com", "name": sub.title()}
        else:
            claims = {"iss": apple.ISSUER, "aud": "com.example.web", "email": f"{sub}@privaterelay.appleid.com"}
        claims.update({"sub": sub, "nonce": nonce, "iat": now, "exp": now + timedelta(minutes=5), **extra})
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test-kid"})


class StartedLogin(NamedTuple):
    state: str
    nonce: str


def fake_code(provider: str, sub: str, nonce: str) -> str:
    return f"{provider}:{sub}:{nonce}"


def split_fake_code(code: str) -> tuple[str, str, str]:
    provider, sub, nonce = code.split(":")
    return provider, sub, nonce


def start_login(client: TestClient, provider: str, **params: str) -> StartedLogin:
    response = client.get(f"/api/auth/{provider}/start", params=params, follow_redirects=False)
    assert response.status_code == 303, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return StartedLogin(query["state"][0], query["nonce"][0])


def login_google(client: TestClient, sub: str, **params: str) -> Any:
    state, nonce = start_login(client, "google", **params)
    params_ = {"state": state, "code": fake_code("google", sub, nonce)}
    return client.get("/api/auth/google/callback", params=params_, follow_redirects=False)


def login_apple(client: TestClient, sub: str, user_field: str | None = None, **params: str) -> Any:
    state, nonce = start_login(client, "apple", **params)
    form = {"state": state, "code": fake_code("apple", sub, nonce)}
    if user_field:
        form["user"] = user_field
    bounce = client.post("/api/auth/apple/callback", data=form, follow_redirects=False)
    assert bounce.status_code == 303, bounce.text
    assert bounce.headers["location"] == f"/api/auth/apple/finish?state={state}"
    return client.get(bounce.headers["location"], follow_redirects=False)


def sql(db_path: Path, statement: str, *params: Any) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
    return rows


def backdate(db_path: Path, table: str, column: str, delta: str, where: str = "1=1") -> None:
    sql(db_path, f"UPDATE {table} SET {column} = datetime('now', ?) WHERE {where}", delta)
