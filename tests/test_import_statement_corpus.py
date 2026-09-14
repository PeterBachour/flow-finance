from __future__ import annotations

from maintenance.import_statement_corpus import StatementProbe, analyze_continuity


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


def test_gap_and_balance_break_are_reported():
    report = analyze_continuity([
        probe('september.pdf', '2025-08-30', '2025-09-30', 346029, 259996),
        probe('november.pdf', '2025-11-01', '2025-11-28', 256504, 251902),
    ])

    assert report['has_period_gap'] is True
    assert report['has_balance_discontinuity'] is True
    assert report['has_period_overlap'] is False
    assert report['issues'][0] == {
        'type': 'period_gap',
        'after_file': 'september.pdf',
        'before_file': 'november.pdf',
        'missing_start': '2025-10-01',
        'missing_end': '2025-10-31',
        'missing_days': 31,
    }
    assert report['issues'][1]['type'] == 'balance_discontinuity'
    assert report['issues'][1]['difference_cents'] == -3492


def test_overlap_is_not_mistaken_for_gap():
    report = analyze_continuity([
        probe('august.pdf', '2024-08-01', '2024-08-30', 45, 242852),
        probe('september.pdf', '2024-08-30', '2024-09-30', 242852, 264085),
    ])

    assert report['has_period_overlap'] is True
    assert report['has_period_gap'] is False
    overlap = report['issues'][0]
    assert overlap['type'] == 'period_overlap'
    assert overlap['overlap_start'] == '2024-08-30'
    assert overlap['overlap_end'] == '2024-08-30'
    assert overlap['overlap_days'] == 1
