# Flow 2.0 — Architecture

## Objectif

Flow 2.0 sépare clairement quatre responsabilités : persistance, moteur financier, API et interface. La base SQLite locale reste la source de vérité opérationnelle. Les imports et Notion alimentent la base ; aucun calcul financier V2 ne dépend d'un accès Notion à l'ouverture.

## Invariants

- `/data/flow.db` n'est jamais supprimée, recréée ou remplacée par une base d'exemple.
- Le ledger des transactions est distinct des snapshots de solde.
- Les transferts internes ne constituent ni revenu ni dépense analytique.
- Une estimation reste identifiée par un niveau de confiance.
- Une simulation n'écrit aucune transaction réelle.
- Les migrations V2 sont additives et idempotentes.

## Couches

### Persistance

`app/db.py` conserve le schéma historique. `app/v2_migrations.py` ajoute uniquement les structures nécessaires à V2 : attributs compte/mouvement/récurrence/objectif, fiches de paie, tags, qualité des données, snapshots de prévision et insights. Les index V2 ciblent les consultations compte/date/catégorie/type et les analyses.

### Moteur financier

`app/financial_engine_v2.py` centralise :

- Safe to Spend jusqu'au prochain revenu structurant ;
- rythme conseillé aujourd'hui et sur 7 jours ;
- point bas et projections engagé/réaliste ;
- confiance de prévision ;
- tendances 3 et 6 mois ;
- synthèse mensuelle ;
- insights basés sur des écarts réels ;
- qualité des données ;
- simulateur de dépense.

Les anciens composants restent disponibles pour compatibilité mais les nouvelles routes V2 consomment le moteur V2.

### API

`app/v2_routes.py` expose `/api/v2/*` : cockpit, mois, tendances, mouvements filtrés et éditables, patrimoine, qualité des données, fiches de paie, simulation et diagnostic.

### Frontend

La navigation principale reste Accueil / Mois / Mouvements / Patrimoine. `static/v2-ui.js` est une couche d'orchestration dédiée à V2 ; `static/v2.css` contient les tokens, dark mode, composants responsive et états d'accessibilité. Les modules d'import existants sont conservés.

## Safe to Spend V2

La capacité totale jusqu'au prochain revenu est :

`point bas prévisionnel - allocations d'objectifs - règles réservées - marge de sécurité`

Le montant affiché pour aujourd'hui est un rythme conseillé :

`Safe to Spend jusqu'au revenu / nombre de jours restants`

Le montant semaine est ce rythme multiplié par sept, plafonné par la capacité totale. Cette distinction évite de présenter une enveloppe de rythme comme une nouvelle source d'argent disponible.

## Confiance

- `confirmed` : >= 90 %
- `probable` : >= 72 %
- `estimated` : >= 50 %
- `uncertain` : < 50 %

Le score est abaissé si le snapshot de solde est ancien ou absent.

## Compatibilité

Flow 2.0 conserve Docker, FastAPI, SQLite, JS/CSS natifs, le service d'update séparé, les imports PDF/CSV, les migrations Notion et la PWA. Aucun framework frontend supplémentaire n'est introduit.
