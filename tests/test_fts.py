from fastapi.testclient import TestClient
from helpers import sql

from linguini.config import Settings


def test_fts_triggers_follow_insert_update_delete(client: TestClient, settings: Settings) -> None:
    db = settings.database_path
    sql(db, "INSERT INTO households(id, name, created_at) VALUES (x'11', 'H', '2026-01-01 00:00:00')")
    sql(
        db,
        "INSERT INTO inventory_items(id, household_id, name, name_normalized, dimension, quantity_base, display_unit,"
        " created_at, updated_at) VALUES (x'22', x'11', 'tejföl', 'tejfol', 'MASS', 0, 'g',"
        " '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
    )
    match = "SELECT rowid FROM inventory_items_fts WHERE inventory_items_fts MATCH ?"
    assert len(sql(db, match, "tejfol")) == 1
    sql(db, "UPDATE inventory_items SET name = 'sajt' WHERE id = x'22'")
    assert sql(db, match, "tejfol") == []
    assert len(sql(db, match, "sajt")) == 1
    sql(db, "DELETE FROM inventory_items WHERE id = x'22'")
    assert sql(db, match, "sajt") == []
