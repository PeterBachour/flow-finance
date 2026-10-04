from __future__ import annotations

import pytest

from maintenance.import_statement_corpus import StatementProbe, analyze_continuity, validate_apply_preflight


def probe(name: str, start: str, end: str, opening: int, closing: int) -> StatementProbe:
    return StatementProbe(
        filename=name,
        path=name,
        period_start=start,
        period_end=end,
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        debit_total_cents=0,
        credit_total_cents=0,
        transaction_count=1,
    )


def test_contiguous_statements_are_clean():
    report = analyze_continuity([
        probe('a.pdf', '2026-01-01', '2026-01-31', 10000, 12000),
        probe('b.pdf', '2026-02-01', '2026-02-28', 12000, 9000),
    ])

    assert report['issues'] == []
    assert report['coverage_start'] == '2026-01-01'
    assert report['coverage_end'] == '2026-02-28'
    assert report['has_period_gap'] is False
    assert report['has_period_overlap'] is False
    assert report['has_balance_discontinuity'] is False
    assert report['status'] == 'ready'
    assert report['can_commit'] is True
    assert report['requires_confirmation'] is False


def test_gap_does_not_report_a_false_balance_break():
    report = analyze_continuity([
        probe('september.pdf', '2025-08-30', '2025-09-30', 346029, 259996),
        probe('november.pdf', '2025-11-01', '2025-11-28', 256504, 251902),
    ])

    assert report['has_period_gap'] is True
    assert report['has_balance_discontinuity'] is False
    assert report['has_period_overlap'] is False
    assert report['issues'][0] == {
        'type': 'period_gap',
        'severity': 'warning',
        'after_file': 'september.pdf',
        'before_file': 'november.pdf',
        'missing_start': '2025-10-01',
        'missing_end': '2025-10-31',
        'missing_days': 31,
    }
    assert report['status'] == 'warning'
    assert report['can_commit'] is True
    assert report['requires_confirmation'] is True
    assert len(report['issues']) == 1


def test_overlap_is_not_mistaken_for_gap():
    report = analyze_continuity([
        probe('august.pdf', '2024-08-01', '2024-08-30', 45, 242852),
        probe('september.pdf', '2024-08-30', '2024-09-30', 242852, 264085),
    ])

    assert report['has_period_overlap'] is True
    assert report['has_period_gap'] is False
    assert report['status'] == 'blocked'
    assert report['can_commit'] is False
    overlap = report['issues'][0]
    assert overlap['type'] == 'period_overlap'
    assert overlap['severity'] == 'blocking'
    assert overlap['overlap_start'] == '2024-08-30'
    assert overlap['overlap_end'] == '2024-08-30'
    assert overlap['overlap_days'] == 1


def test_apply_preflight_requires_confirmation_for_warning_gap():
    probes = [
        probe('september.pdf', '2025-08-30', '2025-09-30', 346029, 259996),
        probe('november.pdf', '2025-11-01', '2025-11-28', 256504, 251902),
    ]

    with pytest.raises(ValueError, match='confirm-warnings'):
        validate_apply_preflight(probes)

    report = validate_apply_preflight(probes, confirm_warnings=True)
    assert report['status'] == 'warning'
    assert report['requires_confirmation'] is True


def test_apply_preflight_blocks_overlaps_even_with_confirmation():
    probes = [
        probe('august.pdf', '2024-08-01', '2024-08-30', 45, 242852),
        probe('september.pdf', '2024-08-30', '2024-09-30', 242852, 264085),
    ]

    with pytest.raises(ValueError, match='blocking'):
        validate_apply_preflight(probes, confirm_warnings=True)
