from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_index_uses_canonical_screen_integrity_without_legacy_overlays():
    html = read("index.html")
    assert "screen-integrity-ui.js?v=" in html
    assert "v5-home-ui.js?v=" in html
    assert "home-canonical-ui.js?v=" not in html
    assert "balance-only-ui.js" not in html
    assert "monthly-cycle-ui.js" not in html


def test_financial_intelligence_matches_monthly_statement_workflow():
    js = read("financial-intelligence-ui.js")
    assert "Relevé mensuel en attente" in js
    assert "Mode estimé normal" in js
    assert "projected_bank_balance_at_horizon_cents" in js
    assert "Importer les mouvements" not in js
    assert "Importe un CSV récent" not in js


def test_decision_budget_uses_unambiguous_financial_concepts():
    js = read("decision-budget-ui.js")
    assert "Safe disponible" in js
    assert "Marge fin de cycle" in js
    assert "Solde projeté" in js
    assert "Plafond protégé" not in js


def test_integrity_ui_separates_hard_issues_from_documentary_reviews():
    js = read("financial-integrity-ui.js")
    assert "hard_issue_count" in js
    assert "review_issue_count" in js
    assert "anomalie(s) bloquante(s)" in js
    assert "revue(s) documentaire(s)" in js


def test_current_month_screen_never_presents_missing_statement_as_zero_spend():
    js = read("screen-integrity-ui.js")
    assert "ne signifie pas 0 € dépensé" in js
    assert "n’affiche donc pas de faux revenus ou dépenses à 0 €" in js
    assert "monthly_statement_pending" not in js or "month_estimated" in js
