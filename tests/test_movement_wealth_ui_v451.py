from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_index_loads_movement_wealth_redesign_assets():
    html = read("index.html")
    assert "movement-wealth.css" in html
    assert "movement-wealth-ui.js" in html
    assert "pre-v5-settings-ui.js" in html
    assert "wealth-clarity-ui.js" not in html


def test_movements_page_prioritizes_historical_financial_reading():
    js = read("movement-wealth-ui.js")
    assert "30 derniers jours" in js
    assert "3 derniers mois" in js
    assert "6 derniers mois" in js
    assert "12 derniers mois" in js
    assert "Moy. dépense" in js
    assert "Top catégorie" in js
    assert "Répartition par catégorie" in js
    assert "/api/v4.6/movements/analysis" in js


def test_wealth_page_exposes_freshness_history_goals_and_manual_refresh():
    js = read("movement-wealth-ui.js")
    assert "Patrimoine net" in js
    assert "Actifs connus" in js
    assert "Dettes renseignées" in js
    assert "Valeurs connues" in js
    assert "À financer" in js
    assert "balance_as_of" in js
    assert "Mettre à jour" in js
    assert "/api/accounts/${id}/balance" in js


def test_balance_update_is_explicit_and_does_not_create_fake_bank_transaction():
    js = read("movement-wealth-ui.js")
    assert "Cette mise à jour crée aussi un snapshot historisé" in js
    assert "Elle ne crée aucun mouvement bancaire" in js
    assert "method:'PUT'" in js
    assert "/api/ledger/transactions" not in js
