from datetime import date
from pathlib import Path
import re

from app.v410_routes import _age_days


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_freshness_age_is_deterministic():
    today = date(2026, 9, 11)
    assert _age_days('2026-09-01', today) == 10
    assert _age_days('2026-07-31', today) == 42
    assert _age_days(None, today) is None


def test_goal_progress_is_snapshotted_and_requires_confirmation():
    text = (ROOT / 'app' / 'v410_routes.py').read_text(encoding='utf-8')
    assert 'goal_progress_history' in text
    assert "pattern='^METTRE_A_JOUR$'" in text
    assert "ON CONFLICT(goal_id,observed_on) DO UPDATE" in text
    assert "source_type TEXT NOT NULL DEFAULT 'manual'" in text


def test_wealth_readiness_ui_exposes_freshness_and_goal_update():
    js = (STATIC / 'wealth-readiness-ui.js').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    version = _runtime_version()
    assert '/api/v4.10/wealth-readiness' in js
    assert '/api/v4.10/goals/${id}/progress' in js
    assert 'METTRE_A_JOUR' in js
    assert f'wealth-readiness-ui.js?v={version}' in html
    assert f'wealth-readiness.css?v={version}' in html


def test_runtime_and_backend_release_are_aligned():
    runtime = (STATIC / 'v4-ui.js').read_text(encoding='utf-8')
    service_worker = (STATIC / 'sw.js').read_text(encoding='utf-8')
    version = _runtime_version()
    assert f"const VERSION='{version}'" in runtime
    assert f"const VERSION='{version}'" in service_worker
    assert f'wealth-readiness-ui.js?v={version}' in service_worker
