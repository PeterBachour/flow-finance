import sqlite3
from pathlib import Path

import pytest

from maintenance.backup_flow_database import create_backup, main


def _database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute('INSERT INTO sample(value) VALUES(?)', ('preserved',))


def test_backup_defaults_to_dry_run_and_writes_nothing(tmp_path):
    source = tmp_path / 'source db.sqlite'
    backup_dir = tmp_path / 'backups'
    _database(source)

    result = create_backup(source, backup_dir)

    assert result['status'] == 'dry_run'
    assert result['source'] == str(source.resolve())
    assert not backup_dir.exists()
    assert not Path(result['destination']).exists()


def test_apply_creates_private_integrity_checked_backup_without_changing_source(tmp_path):
    source = tmp_path / 'source db.sqlite'
    backup_dir = tmp_path / 'backups'
    _database(source)

    result = create_backup(source, backup_dir, apply=True)

    backup = Path(result['destination'])
    assert result['status'] == 'created'
    assert result['integrity'] == 'ok'
    assert backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600

    with sqlite3.connect(backup) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('SELECT value FROM sample').fetchone()[0] == 'preserved'
    with sqlite3.connect(source) as conn:
        assert conn.execute('SELECT value FROM sample').fetchone()[0] == 'preserved'


def test_cli_does_not_write_without_apply(tmp_path, capsys):
    source = tmp_path / 'flow.db'
    backup_dir = tmp_path / 'backups'
    _database(source)

    assert main(['--db', str(source), '--backup-dir', str(backup_dir)]) == 0
    assert 'status=dry_run' in capsys.readouterr().out
    assert not backup_dir.exists()


def test_backup_refuses_missing_database(tmp_path, capsys):
    assert main(['--db', str(tmp_path / 'missing.db'), '--backup-dir', str(tmp_path / 'backups')]) == 2
    assert 'Source database not found' in capsys.readouterr().err
