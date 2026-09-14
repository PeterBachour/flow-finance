# Flow 2.0.0

## Fonctionnel

- Cockpit de décision enrichi avec Safe to Spend aujourd'hui, 7 jours et jusqu'au prochain revenu.
- Statut confortable / prudent / serré / critique.
- Explication détaillée du calcul et score de confiance.
- Pilotage mensuel avec fixes, variables, épargne, comparaison au mois précédent et tendances par catégorie.
- Tendances 3 mois / 6 mois et insights uniquement basés sur les transactions réelles.
- Mouvements filtrables par catégorie, type et drapeaux, avec modification du libellé utilisateur, catégorie, type, transfert interne, exception et exclusion analytique.
- Patrimoine enrichi avec séparation cash, épargne disponible, épargne bloquée, investissements et dettes.
- Modèle de fiches de paie dédié.
- Centre de qualité des données et diagnostic sans secret.
- Dark mode clair / sombre / système.

## Architecture

- Nouveau moteur `financial_engine_v2.py`.
- Nouvelles routes `/api/v2/*`.
- Migration additive `v2_migrations.py`.
- UI complémentaire `v2-ui.js` et design system `v2.css`.
- Index SQLite supplémentaires pour les lectures V2.

## PWA

- Version synchronisée à `2.0.0`.
- Cache `flow-v2.0.0`.
- Manifest et URLs d'icônes versionnés.
- Icônes PNG 192, 512, maskable 512 et Apple touch icon désormais stockées directement dans le repo.
- Docker ne génère plus les icônes à chaque build.

## Tests ajoutés

- migration additive et idempotente ;
- conservation des lignes existantes ;
- niveaux de confiance et Safe to Spend ;
- exclusion des transferts internes et lignes exclues des analyses ;
- cohérence de version backend / manifest / service worker / UI.
