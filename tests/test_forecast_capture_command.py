from contextlib import contextmanager
from datetime import date

import maintenance.capture_forecast_snapshot as command


def test_capture_command_passes_explicit_local_date_to_service(monkeypatch, capsys):
    seen = {}

    @contextmanager
    def fake_connection():
        yield object()

    def fake_capture(conn, *, as_of):
        seen['as_of'] = as_of
        return {'status': 'captured', 'as_of': as_of.isoformat(), 'captured_modes': ['engaged', 'realistic', 'prudent']}

    monkeypatch.setattr(command, 'connection', fake_connection)
    monkeypatch.setattr(command, 'ensure_v2_schema', lambda conn: None)
    monkeypatch.setattr(command, 'capture_daily_forecast', fake_capture)

    assert command.main(['--as-of', '2026-09-27']) == 0
    assert seen['as_of'] == date(2026, 9, 27)
    assert 'status=captured as_of=2026-09-27' in capsys.readouterr().out


def test_capture_command_returns_failure_when_forecast_is_unavailable(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def fake_connection():
        yield object()

    monkeypatch.setattr(command, 'connection', fake_connection)
    monkeypatch.setattr(command, 'ensure_v2_schema', lambda conn: None)
    monkeypatch.setattr(
        command,
        'capture_daily_forecast',
        lambda conn, *, as_of: {
            'status': 'unavailable',
            'as_of': as_of.isoformat(),
            'reason': 'stale_balance',
            'captured_modes': [],
        },
    )

    assert command.main(['--as-of', '2026-09-27']) == 2
