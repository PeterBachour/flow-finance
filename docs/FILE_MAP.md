# Carte du dépôt

## Point d'entrée

- `app/main.py` : application FastAPI, middleware, montage du frontend et assemblage des routes.
- `app/version.py` : version applicative exposée par l'API.
- `app/static/index.html` : shell de la PWA.
- `app/static/app.css` : design system actif.
- `app/static/v4-ui.js` : runtime principal consolidé.
- `app/static/sw.js` : cache et cycle de mise à jour PWA.
- `app/static/manifest.webmanifest` : manifeste installable.

## Données

- `app/db.py` : schéma historique, connexions et initialisation.
- `app/v2_migrations.py`, `app/v3_migrations.py`, `app/v22_migrations.py`, `app/v31_migrations.py`, `app/v32_migrations.py`, `app/v34_migrations.py`, `app/v36_migrations.py`, `app/v37_migrations.py` : migrations additives.
- `app/import_identity.py` : identité de source et anti-doublon.
- `app/data_reconciliation.py` : rapprochement.
- `app/spending_classification.py` : classification analytique.
- `app/transfer_intelligence.py` : transferts internes.

## Calculs financiers

- `app/financial_engine_v2.py` : moteur de synthèse central.
- `app/safe_to_spend.py` : capacité de dépense sécurisée.
- `app/forecast.py` : projection de trésorerie.
- `app/monthly_finance.py` : calculs mensuels.
- `app/trend_engine.py` : tendances.
- `app/financial_integrity.py` : contrôles comptables.
- `app/financial_intelligence.py` et `app/data_intelligence.py` : analyses et insights.
- `app/commitment_engine.py` : engagements.
- `app/v5_engine.py`, `app/v5_planning.py`, `app/v5_predictive.py`, `app/v5_recommendations.py` : cockpit V5.

## Imports et qualité

- `app/imports.py` : import historique.
- `app/import_routes.py` : API d'import.
- `app/bulk_import.py` : staging multi-documents.
- `app/lcl_parser_v2.py` : lecture des relevés LCL.
- `app/payroll_reconciliation.py` : rapprochement des fiches de paie.
- `app/history_coverage.py` : couverture documentaire.
- `app/history_readiness.py` : aptitude de l'historique aux analyses.
- `app/data_quality_report.py` : diagnostic qualité.
- `app/data_quality_actions.py` : file d'actions V5.7.

## Routes

Les fichiers `app/*_routes.py` exposent les domaines fonctionnels. Les fichiers `app/v*_routes.py` portent les contrats versionnés. Avant d'ajouter une route, vérifier qu'un domaine ou une version existante peut être étendu sans duplication.

## Interface

- `app/static/app.js` : fonctions frontend communes.
- `app/static/v4-ui.js` : navigation et écrans consolidés.
- `app/static/v5-*.js` : vues décisionnelles V5.
- `app/static/v57-data-quality-ui.js` : centre de qualité V5.7.
- `app/static/imports-ui.js` et `bulk-import-ui.js` : imports.
- `app/static/app.css` et fichiers CSS fonctionnels : styles actifs.

Les anciens fichiers versionnés restent présents pour compatibilité ou historique. Vérifier leur chargement réel dans `index.html` avant toute modification.

## Maintenance

- `maintenance/update_helper.py` : mise à jour contrôlée.
- `install-update-helper.sh` : installation du service système.
- `maintenance/audit_financial_integrity.py` : audit comptable.
- `maintenance/audit_history_coverage.py` : audit de couverture.
- `maintenance/reconcile_import_reviews.py` : rapprochement des revues, dry-run par défaut.
- `maintenance/backfill_statement_balance_snapshots.py` : reconstruction idempotente des snapshots.

Les scripts préfixés `audit_` doivent rester en lecture seule. Les scripts préfixés `apply_` ne doivent écrire qu'après argument explicite et sauvegarde adaptée.

## Tests

- `tests/conftest.py` : fixtures communes.
- `tests/test_financial_engine_v2.py` : moteur financier.
- `tests/test_financial_integrity_v420.py` : intégrité.
- `tests/test_import_*.py` : imports.
- `tests/test_v*_migration.py` : migrations.
- `tests/test_v5_*.py` et `tests/test_v5*_*.py` : releases et parcours V5.
- `tests/test_v57_release_final.py` : cohérence finale 5.7.

## Fichiers à ne pas ouvrir ou modifier sans nécessité

- données runtime sous `data/` ;
- bases `*.db`, `*.sqlite`, `*.sqlite3` ;
- `.env` ;
- documents financiers personnels ;
- caches et fichiers générés.
