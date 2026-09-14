#!/usr/bin/env python3
"""Safe maintenance tooling for Flow Finance SQLite data.

Commands:
  backup       Create a timestamped SQLite backup and run integrity_check.
  verify-empty Build a temporary database from the current schema and verify it.
  rebuild      Create a fresh database only after a backup; requires --confirm-rebuild.

This script never deletes backups automatically.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DB = Path(os.getenv("FLOW_DB_PATH", PROJECT_ROOT / "data" / "flow.db"))
DEFAULT_BACKUP_DIR = Path(os.getenv("FLOW_BACKUP_DIR", "/var/lib/flow-finance-maintenance/backups"))


def integrity_check(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row else "unknown")


def sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"Active DB not found: {db_path}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"flow-before-rebuild-{stamp}.db"
    sqlite_backup(db_path, target)
    result = integrity_check(target)
    if result.lower() != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Backup integrity check failed: {result}")
    return target


def build_fresh_database(target: Path) -> None:
    """Build a fresh Flow DB at target without touching the active database.

    app.db resolves DB_PATH at import time. Tests and maintenance commands may already
    have imported that module, so changing only FLOW_DB_PATH is not sufficient. Override
    the module-level Path explicitly for the duration of init_db(), then restore it.
    """
    from app import db

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    original_path = db.DB_PATH
    try:
        db.DB_PATH = target
        db.init_db()
    finally:
        db.DB_PATH = original_path


def verify_empty_database() -> dict:
    with tempfile.TemporaryDirectory(prefix="flow-db-check-") as tmp:
        path = Path(tmp) / "flow.db"
        build_fresh_database(path)
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            goal_count = conn.execute("SELECT COUNT(*) FROM financial_goals").fetchone()[0]
            account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            goal_indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(financial_goals)").fetchall()
            }
        required = {
            "accounts",
            "transactions",
            "planned_transactions",
            "recurring_transactions",
            "financial_goals",
            "settings",
        }
        missing = sorted(required - tables)
        return {
            "integrity": integrity,
            "missing_tables": missing,
            "financial_rows": {
                "accounts": account_count,
                "transactions": tx_count,
                "financial_goals": goal_count,
            },
            "goal_source_key_index": "idx_goals_source_key" in goal_indexes,
        }


def rebuild_database(db_path: Path, backup_dir: Path, confirmed: bool) -> tuple[Path, dict]:
    if not confirmed:
        raise RuntimeError("Refusing rebuild without --confirm-rebuild")
    backup = backup_database(db_path, backup_dir)
    staging = db_path.with_suffix(".rebuild.tmp")
    staging.unlink(missing_ok=True)
    build_fresh_database(staging)
    check = integrity_check(staging)
    if check.lower() != "ok":
        staging.unlink(missing_ok=True)
        raise RuntimeError(f"Fresh DB integrity check failed: {check}")
    shutil.move(str(staging), str(db_path))
    return backup, verify_empty_database_at(db_path)


def verify_empty_database_at(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return {
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "accounts": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            "financial_goals": conn.execute("SELECT COUNT(*) FROM financial_goals").fetchone()[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Flow Finance database administration")
    parser.add_argument("command", choices=("backup", "verify-empty", "rebuild"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--confirm-rebuild", action="store_true")
    args = parser.parse_args()

    if args.command == "backup":
        target = backup_database(args.db, args.backup_dir)
        print(f"active_db={args.db}")
        print(f"active_size={args.db.stat().st_size}")
        print(f"backup={target}")
        print(f"backup_size={target.stat().st_size}")
        print(f"integrity={integrity_check(target)}")
        return 0

    if args.command == "verify-empty":
        result = verify_empty_database()
        for key, value in result.items():
            print(f"{key}={value}")
        if result["integrity"] != "ok" or result["missing_tables"] or not result["goal_source_key_index"]:
            return 2
        if any(result["financial_rows"].values()):
            print("error=fresh database contains financial data")
            return 3
        return 0

    backup, result = rebuild_database(args.db, args.backup_dir, args.confirm_rebuild)
    print(f"backup={backup}")
    print(f"active_db={args.db}")
    print(f"verification={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
