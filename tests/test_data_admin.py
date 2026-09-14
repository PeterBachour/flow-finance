import sqlite3
from pathlib import Path

from maintenance.data_admin import backup_database, build_fresh_database, integrity_check, verify_empty_database_at


def test_fresh_database_has_no_financial_rows(tmp_path: Path):
    db_path = tmp_path / "flow.db"
    build_fresh_database(db_path)
    result = verify_empty_database_at(db_path)
    assert result["integrity"] == "ok"
    assert result["accounts"] == 0
    assert result["transactions"] == 0
    assert result["financial_goals"] == 0


def test_financial_goals_source_key_unique_index_exists(tmp_path: Path):
    db_path = tmp_path / "flow.db"
    build_fresh_database(db_path)
    with sqlite3.connect(db_path) as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(financial_goals)")}
    assert "idx_goals_source_key" in indexes


def test_backup_is_integrity_checked_and_preserves_source(tmp_path: Path):
    db_path = tmp_path / "flow.db"
    backup_dir = tmp_path / "backups"
    build_fresh_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO accounts(name,current_balance_cents) VALUES('Test',12345)")
        conn.commit()
    original_size = db_path.stat().st_size
    backup = backup_database(db_path, backup_dir)
    assert db_path.exists()
    assert backup.exists()
    assert db_path.stat().st_size == original_size
    assert integrity_check(backup) == "ok"
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT current_balance_cents FROM accounts WHERE name='Test'").fetchone()[0] == 12345
