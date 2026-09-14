from pathlib import Path

from app import update_routes
from app.version import VERSION


def test_release_version_keeps_v03_compatibility():
    assert tuple(map(int, VERSION.split('.'))) >= (0, 3, 0)


def test_update_disabled_without_helper(monkeypatch, tmp_path: Path):
    monkeypatch.setenv('FLOW_UPDATE_ENABLED', '0')
    monkeypatch.setattr(update_routes, 'MAINTENANCE', tmp_path)
    assert update_routes.enabled() is False
    status = update_routes.update_status()
    assert status['current_version'] == VERSION
    assert status['enabled'] is False
