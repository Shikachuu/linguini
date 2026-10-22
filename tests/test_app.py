import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from linguini.config import Settings


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_config_reports_enabled_providers(client: TestClient) -> None:
    assert client.get("/api/config").json()["providers"] == {"google": True, "apple": True}


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    response = client.get("/api/nope", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_root_without_frontend(client: TestClient) -> None:
    assert "No frontend" in client.get("/").json()["detail"]


def test_migrations_create_wal_db_with_fts(client: TestClient, settings: Settings) -> None:
    conn = sqlite3.connect(settings.database_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "households", "inventory_items", "inventory_items_fts", "runs", "alembic_version"} <= tables


def test_spa_fallback(tmp_path: Path) -> None:
    from pydantic import SecretStr

    from linguini.app import create_app

    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "assets" / "app.js").write_text("1")
    settings = Settings(secret_key=SecretStr("x"), data_dir=tmp_path / "data", static_dir=static)
    with TestClient(create_app(settings)) as client:
        deep = client.get("/households/abc", headers={"Accept": "text/html"})
        assert deep.status_code == 200
        assert "spa" in deep.text
        assert deep.headers["cache-control"] == "no-cache"
        asset = client.get("/assets/app.js")
        assert asset.headers["cache-control"].startswith("public, max-age=31536000")
        assert client.get("/api/health").json() == {"status": "ok"}
