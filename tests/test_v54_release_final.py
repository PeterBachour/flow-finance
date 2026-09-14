from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v54_release_keeps_automation_and_import_cleanup_regressions():
    expected_tests = {
        'test_v54_automation.py',
        'test_v54_high_confidence_cleanup.py',
        'test_v54_import_review_cleanup.py',
    }
    test_dir = ROOT / 'tests'
    assert expected_tests.issubset({path.name for path in test_dir.glob('test_v54_*.py')})


def test_v54_safety_contracts_remain_present_after_release_progression():
    automation = (ROOT / 'tests' / 'test_v54_automation.py').read_text(encoding='utf-8')
    cleanup = (ROOT / 'tests' / 'test_v54_import_review_cleanup.py').read_text(encoding='utf-8')
    integrity = (ROOT / 'maintenance' / 'audit_financial_integrity.py').read_text(encoding='utf-8')

    assert 'test_update_helper_tests_built_image_before_runtime_restart' in automation
    assert 'test_reconciliation_tool_is_dry_run_by_default' in cleanup
    assert '--fail-on-hard' in integrity
