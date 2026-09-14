import sqlite3
from datetime import date
from pathlib import Path

from app.financial_visualization import build_variable_category_view


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_variable_category_view_uses_only_closed_month_variable_consumption():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE recurring_transactions(label TEXT, detection_status TEXT, amount_cents INTEGER);
        CREATE TABLE transactions(
            booking_date TEXT,
            amount_cents INTEGER,
            label TEXT,
            category TEXT,
            transaction_type TEXT,
            is_internal_transfer INTEGER,
            status TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO transactions VALUES(?,?,?,?,?,?,?)",
        [
            ("2026-08-05", -5000, "Restaurant", "Restaurants", None, 0, "confirmed"),
            ("2026-08-06", -3000, "Courses", "Alimentation", None, 0, "confirmed"),
            ("2026-08-07", -999, "SFR", "Télécom", None, 0, "confirmed"),
            ("2026-09-02", -9000, "Restaurant septembre", "Restaurants", None, 0, "confirmed"),
        ],
    )

    result = build_variable_category_view(conn, as_of=date(2026, 9, 11), months=3)

    assert result["total_variable_cents"] == 8000
    assert result["categories"][0] == {
        "category": "Restaurants",
        "amount_cents": 5000,
        "share_pct": 62.5,
    }
    assert all(item["month"] != "2026-09" for item in result["monthly_variable"])


def test_v450_visualization_ui_is_wired_and_read_only():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "financial-visualization-ui.js").read_text(encoding="utf-8")
    css = (STATIC / "financial-visualization.css").read_text(encoding="utf-8")

    assert "/static/financial-visualization-ui.js?v=" in html
    assert "/static/financial-visualization.css?v=" in html
    assert "/api/finance/visualization?months=6" in js
    assert "projected_bank_balance_at_horizon_cents" in js
    assert "3 mois" in js or "['3m','6m','12m']" in js
    assert "fetch('/api/finance/visualization" in js
    assert "method:'POST'" not in js
    assert "fv-line-path" in css


def test_v450_copy_distinguishes_estimate_from_consolidated_data():
    js = (STATIC / "financial-visualization-ui.js").read_text(encoding="utf-8")
    assert "Mois estimé" in js
    assert "reste estimative tant que le relevé du mois courant n’est pas consolidé" in js
    assert "ne transforme pas la variation de solde en catégories fictives" in js
