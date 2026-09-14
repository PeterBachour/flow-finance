# Flow Finance

Flow Finance est une PWA personnelle de pilotage financier, auto-hébergée et orientée décision.

Sa question centrale est :

> Combien puis-je réellement dépenser aujourd'hui sans compromettre mes échéances, mon épargne, mes objectifs et ma fin de mois ?

## État du projet

- Version applicative : `5.7.0`
- Dépôt de référence : `PeterBachour/flow-finance`
- Branche de référence : `main`
- Runtime cible : Raspberry Pi 4 sous Debian 13
- Port HTTP : `8010`
- Base de données : SQLite persistée hors de l'image Docker
- Interface : PWA mobile-first en HTML, CSS et JavaScript natifs
- API : FastAPI
- Déploiement : Docker Compose

Le code a été extrait du dossier historique `flow-finance/` du monorepo `PeterBachour/coaster-collection`. Ce dépôt dédié devient la source de vérité du code de Flow. L'ancien dossier ne doit plus recevoir de nouveaux développements.

## Principes produit

Flow n'est pas un simple tableau de comptes. L'application doit :

1. partir des données réellement constatées ;
2. distinguer clairement faits, prévisions, hypothèses et simulations ;
3. expliquer chaque indicateur financier important ;
4. préserver l'historique et la traçabilité des imports ;
5. exiger une validation explicite avant toute correction financière ;
6. transformer les données en décisions compréhensibles ;
7. rester utilisable sur iPhone, iPad et ordinateur.

## Fonctionnalités disponibles

### Cockpit et Safe to Spend

- disponibilité sécurisée jusqu'au prochain revenu structurant ;
- rythme conseillé aujourd'hui et sur sept jours ;
- point bas prévisionnel ;
- niveau de confiance ;
- mode `balance-only` quand l'historique courant est insuffisant ;
- carte « Pourquoi ce montant ? » détaillant le calcul ;
- recommandations et centre de décision.

Le calcul protège les échéances planifiées, charges récurrentes, réservations explicites, objectifs réellement engagés et marge de sécurité. Un objectif déjà financé ne doit jamais être déduit une seconde fois.

### Pilotage mensuel

- synthèse des revenus, charges fixes, dépenses variables et épargne ;
- comparaison avec les mois précédents ;
- budgets adaptatifs ;
- préparation et clôture mensuelles ;
- tendances sur plusieurs horizons ;
- analyse des écarts ;
- catégorisation analytique.

### Mouvements et imports

- recherche et filtres ;
- édition contrôlée des métadonnées analytiques ;
- import PDF LCL et CSV ;
- bulk import jusqu'à 100 documents ;
- staging sans écriture avant confirmation ;
- détection des doublons par identité de source ;
- rapprochement et revue manuelle ;
- classification des transferts internes, remboursements, dépenses exceptionnelles, épargne et consommation.

Les documents sources ne doivent pas être ajoutés au dépôt Git. Les relevés bancaires, fiches de paie et exports contiennent des données personnelles et restent dans les emplacements runtime prévus.

### Qualité et intégrité des données

- contrôle de l'équation comptable des relevés ;
- vérification des snapshots de clôture ;
- détection des périodes manquantes ;
- audit de la couverture des relevés et fiches de paie ;
- History Readiness Gate ;
- Data Quality Action Center ;
- preuves et actions de remédiation ;
- outils de maintenance en lecture seule ou en dry-run par défaut.

### Prévision, scénarios et patrimoine

- projection de trésorerie ;
- simulations sans écriture dans le ledger réel ;
- scénarios persistants ;
- suivi des objectifs ;
- comptes, liquidités, épargne, investissements et dettes ;
- projection patrimoniale ;
- séparation des transferts et de la consommation.

### PWA et exploitation

- installation sur l'écran d'accueil ;
- manifest et icônes versionnés ;
- cache contrôlé par service worker ;
- endpoint de version ;
- healthcheck Docker ;
- mise à jour depuis l'interface via un service de maintenance séparé ;
- validation de l'image avant redémarrage ;
- rollback en cas d'échec du runtime.

## Architecture

```text
flow-finance/
├── app/
│   ├── main.py                 # application FastAPI et assemblage des routes
│   ├── db.py                   # schéma historique et accès SQLite
│   ├── financial_engine_v2.py  # moteur financier central V2
│   ├── safe_to_spend.py        # calculs Safe to Spend
│   ├── forecast.py             # prévisions
│   ├── imports.py              # ingestion historique
│   ├── bulk_import.py          # imports multi-documents
│   ├── financial_integrity.py  # contrôles comptables
│   ├── history_coverage.py     # couverture documentaire
│   ├── data_quality_actions.py # plan de remédiation V5.7
│   ├── v*_migrations.py        # migrations additives
│   ├── v*_routes.py            # contrats API versionnés
│   └── static/                 # interface, styles, manifest et service worker
├── maintenance/                # audits, corrections contrôlées et updater
├── tests/                      # tests métier, API, migration, UI et release
├── docs/
│   └── FILE_MAP.md             # carte de lecture du code
├── ARCHITECTURE_V2.md
├── CHANGELOG.md
├── RELEASE_V1.md
├── RELEASE_V2.md
├── AGENTS.md                   # règles impératives de contribution
├── Dockerfile
├── docker-compose.yml
├── install-update-helper.sh
├── requirements.txt
└── README.md
```

Les couches principales sont :

1. persistance SQLite et migrations additives ;
2. moteurs financiers déterministes ;
3. API FastAPI versionnée ;
4. interface PWA native ;
5. maintenance séparée du runtime applicatif.

## Modèle de données et invariants

La base locale est la source de vérité opérationnelle. Notion et les documents importés sont des sources d'alimentation, jamais des dépendances nécessaires au calcul à chaque ouverture.

Invariants obligatoires :

- `/data/flow.db` ne doit jamais être supprimée, recréée ou remplacée automatiquement ;
- toutes les sommes monétaires sont traitées de façon déterministe, sans flottants non maîtrisés ;
- les migrations sont additives, idempotentes et compatibles avec les données existantes ;
- le ledger des transactions est distinct des snapshots de solde ;
- un transfert interne n'est ni un revenu ni une dépense analytique ;
- un remboursement n'est pas un revenu structurel ;
- une simulation ne crée aucune transaction réelle ;
- une estimation conserve son niveau de confiance ;
- une correction financière exige une confirmation explicite ;
- aucune donnée fictive ne doit contaminer la base réelle.

## Installation sur Raspberry Pi

### Prérequis

- Debian 13 64 bits ;
- Git ;
- Docker Engine ;
- plugin Docker Compose.

### Première installation

```bash
cd /home/pi
git clone https://github.com/PeterBachour/flow-finance.git
cd flow-finance
mkdir -p data
FLOW_GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
```

Vérification :

```bash
docker compose ps
curl http://localhost:8010/api/health
curl http://localhost:8010/api/version
```

Accès depuis le réseau local :

```text
http://<adresse-ip-du-raspberry>:8010
```

### Migration depuis l'ancien monorepo

Le dossier persistant ne doit pas être déplacé à l'aveugle. Arrêter l'ancien conteneur, sauvegarder la base, copier les données vers le nouveau dossier puis vérifier l'intégrité avant reprise.

Exemple de sauvegarde non destructive :

```bash
mkdir -p /home/pi/flow-finance-backups
cp -a /home/pi/coaster-collection/flow-finance/data/flow.db \
  /home/pi/flow-finance-backups/flow-$(date +%Y%m%d-%H%M%S).db
```

La configuration Docker du dépôt monte :

- `./data:/data` ;
- `/var/lib/flow-finance-maintenance:/maintenance`.

## Mise à jour

Mise à jour manuelle :

```bash
cd /home/pi/flow-finance
git pull --ff-only origin main
FLOW_GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
docker compose ps
curl http://localhost:8010/api/health
```

Installation du service de mise à jour depuis l'interface :

```bash
cd /home/pi/flow-finance
chmod +x install-update-helper.sh
./install-update-helper.sh
```

Le service de maintenance doit rester séparé du conteneur principal. Une mise à jour doit construire et tester la nouvelle image avant de remplacer le runtime actif.

## Tests et contrôles

Installation locale :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Contrôle syntaxique :

```bash
python -m compileall -q app maintenance tests
```

Audit financier :

```bash
python maintenance/audit_financial_integrity.py --db /data/flow.db
```

Couverture historique :

```bash
python maintenance/audit_history_coverage.py --db /data/flow.db --months 24
```

Le mode bloquant est réservé à un contrôle volontaire :

```bash
python maintenance/audit_history_coverage.py \
  --db /data/flow.db \
  --months 24 \
  --fail-on-gaps
```

Les scripts capables de modifier des données doivent fonctionner en dry-run par défaut et nécessiter un argument explicite tel que `--apply`.

## Règles de développement

Avant toute modification :

1. lire `AGENTS.md` ;
2. lire `docs/FILE_MAP.md` ;
3. identifier les fichiers et symboles concernés ;
4. vérifier l'état de la branche `main` ;
5. préserver les données persistantes ;
6. limiter le changement au besoin demandé.

Pour chaque changement :

- réutiliser les moteurs, routes et composants existants ;
- ne pas créer une nouvelle version d'un module lorsqu'une consolidation suffit ;
- conserver les contrats API existants ou documenter explicitement la rupture ;
- ajouter un test déterministe pour chaque règle financière ;
- tester la migration avec une base existante ;
- synchroniser la version backend, frontend, manifest et cache PWA ;
- ne jamais masquer l'incertitude d'un calcul ;
- ne jamais exécuter automatiquement une recommandation financière ;
- maintenir l'accessibilité et le responsive mobile-first ;
- documenter une release dans `CHANGELOG.md` et `app/static/changelog.json`.

## Convention de contribution

Branches :

```text
feat/<sujet>
fix/<sujet>
docs/<sujet>
chore/<sujet>
```

Messages de commit :

```text
feat: add forecast confidence breakdown
fix: prevent duplicate goal allocation
docs: document dedicated repository migration
test: cover balance-only safe-to-spend calculation
```

Une modification est terminée lorsque :

- le comportement demandé est implémenté ;
- les tests ciblés passent ;
- les invariants financiers sont préservés ;
- aucune donnée personnelle ou runtime n'est versionnée ;
- la documentation affectée est mise à jour ;
- le démarrage Docker et les endpoints de santé sont valides.

## Sécurité et confidentialité

Ne jamais versionner :

- `.env` ;
- `data/` ;
- `flow.db` ou toute sauvegarde SQLite ;
- relevés bancaires ;
- fiches de paie ;
- exports Notion ;
- clés API, jetons, identifiants ou secrets ;
- journaux contenant des données personnelles.

Les réponses API de diagnostic ne doivent jamais exposer de secret. Les données financières doivent rester locales au Raspberry Pi, sauf action explicite et contrôlée.

## Documentation associée

- `ARCHITECTURE_V2.md` : principes de séparation des responsabilités ;
- `CHANGELOG.md` : historique des versions ;
- `RELEASE_V1.md` et `RELEASE_V2.md` : jalons historiques ;
- `docs/FILE_MAP.md` : orientation rapide dans le code ;
- `AGENTS.md` : règles obligatoires pour les agents et contributeurs.
