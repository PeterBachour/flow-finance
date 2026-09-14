from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent


def test_github_flow_ci_builds_image_runs_tests_and_smokes_runtime():
    workflow_path = REPOSITORY / '.github' / 'workflows' / 'flow-finance-ci.yml'
    if not workflow_path.exists():
        return  # The production image intentionally contains only flow-finance/.
    workflow = workflow_path.read_text(encoding='utf-8')
    assert "'flow-finance/**'" in workflow
    assert 'docker build' in workflow
    assert '--entrypoint pytest' in workflow
    assert '/api/health' in workflow
    assert '/api/version' in workflow
    assert 'contents: read' in workflow


def test_update_helper_tests_built_image_before_runtime_restart():
    source = (ROOT / 'maintenance' / 'update_helper.py').read_text(encoding='utf-8')
    update = source[source.index('def update_locked():'):]
    test_position = update.index('test_summary = test_built_image(image_id)')
    restart_position = update.index("'compose', 'up', '-d', '--no-deps'")
    assert test_position < restart_position
    assert "write('testing'" in update
    assert "tests='passed'" in update


def test_installer_enables_read_only_daily_audit_timer():
    source = (ROOT / 'install-update-helper.sh').read_text(encoding='utf-8')
    assert 'flow-finance-audit.service' in source
    assert 'flow-finance-audit.timer' in source
    assert 'OnCalendar=*-*-* 04:15:00' in source
    assert 'audit_financial_integrity.py --db /data/flow.db --fail-on-hard' in source
    assert '--apply' not in source



def test_scheduled_audit_exit_code_ignores_reviews_but_fails_on_hard_issues():
    from maintenance.audit_financial_integrity import exit_code

    audit_source = (ROOT / 'maintenance' / 'audit_financial_integrity.py').read_text(
        encoding='utf-8'
    )
    assert "parser.add_argument('--fail-on-hard'" in audit_source
    review = {'status': 'review', 'hard_issue_count': 0}
    hard_failure = {'status': 'warning', 'hard_issue_count': 1}
    assert exit_code(review, fail_on_hard=True) == 0
    assert exit_code(hard_failure, fail_on_hard=True) == 1
