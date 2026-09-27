#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / 'data' / 'flow.db'
DEFAULT_BACKUP_DIR = PROJECT_ROOT.parent / 'flow-finance-backups'


def create_backup(database: Path, backup_dir: Path, *, apply: bool = False) -> dict:
    source = database.expanduser().resolve()
    destination_dir = backup_dir.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f'Source database not found: {source}')

    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')
    destination = destination_dir / f'flow-{stamp}.db'
    if source == destination:
        raise ValueError('Backup destination must differ from the source database.')

    if not apply:
        return {
            'status': 'dry_run',
            'source': str(source),
            'destination': str(destination),
        }

    destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite existing backup: {destination}')

    temp_path = None
    source_uri = f'file:{quote(source.as_posix(), safe="/")}?mode=ro'
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination_dir,
            prefix=f'.{destination.stem}-',
            suffix='.tmp',
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        with sqlite3.connect(source_uri, uri=True, timeout=30) as source_conn:
            with sqlite3.connect(temp_path, timeout=30) as backup_conn:
                source_conn.backup(backup_conn, pages=256, sleep=0.01)
                integrity = backup_conn.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity != 'ok':
                    raise sqlite3.DatabaseError(f'Backup integrity check failed: {integrity}')
        os.chmod(temp_path, 0o600)
        os.link(temp_path, destination)
        temp_path.unlink()
        temp_path = None
        return {
            'status': 'created',
            'source': str(source),
            'destination': str(destination),
            'bytes': destination.stat().st_size,
            'integrity': 'ok',
        }
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Create and verify a consistent SQLite backup of Flow Finance.'
    )
    parser.add_argument('--db', type=Path, default=DEFAULT_DATABASE, help='Source SQLite database')
    parser.add_argument('--backup-dir', type=Path, default=DEFAULT_BACKUP_DIR, help='Backup destination directory')
    parser.add_argument('--apply', action='store_true', help='Write the verified backup; without this flag only show the planned path')
    args = parser.parse_args(argv)

    try:
        result = create_backup(args.db, args.backup_dir, apply=args.apply)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f'error={exc}', file=sys.stderr)
        return 2

    print(f"status={result['status']} destination={result['destination']}")
    if result['status'] == 'created':
        print(f"bytes={result['bytes']} integrity={result['integrity']}")
    else:
        print('No file written. Repeat with --apply to create the backup.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
