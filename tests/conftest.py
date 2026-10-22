import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt.algorithms
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from helpers import IdToken, split_fake_code
from pydantic import SecretStr

from linguini.app import create_app
from linguini.auth import apple, google
from linguini.config import Settings

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks(rsa_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True)
    jwk.update({"kid": "test-kid", "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture(scope="session")
def apple_private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@pytest.fixture
def settings(tmp_path: Path, apple_private_key_pem: str) -> Settings:
    return Settings(
        secret_key=SecretStr("test-secret"),
        data_dir=tmp_path / "data",
        google_client_id="google-web",
        google_client_secret=SecretStr("google-secret"),
        google_extra_audiences=["google-ios"],
        apple_team_id="TEAM",
        apple_key_id="KEY",
        apple_private_key=SecretStr(apple_private_key_pem),
        apple_services_id="com.example.web",
        apple_bundle_ids=["com.example.ios"],
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def id_token(rsa_key: rsa.RSAPrivateKey) -> IdToken:
    return IdToken(rsa_key)


@pytest.fixture
def providers(jwks: dict[str, Any], id_token: IdToken) -> Iterator[respx.MockRouter]:
    def token_response(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        provider, sub, nonce = split_fake_code(form["code"][0])
        extra = {"aud": form["client_id"][0]} if provider == "apple" else {}
        body = {"id_token": id_token(provider, sub, nonce, **extra), "access_token": "at", "expires_in": 3600}
        if provider == "apple":
            body["refresh_token"] = f"apple-refresh-{sub}"
        return httpx.Response(200, json=body)

    with respx.mock(assert_all_called=False) as router:
        router.get(google.JWKS_URL).mock(return_value=httpx.Response(200, json=jwks))
        router.get(apple.JWKS_URL).mock(return_value=httpx.Response(200, json=jwks))
        router.post(google.TOKEN_URL).mock(side_effect=token_response)
        router.post(apple.TOKEN_URL).mock(side_effect=token_response)
        router.post(apple.REVOKE_URL).mock(return_value=httpx.Response(200))
        yield router
