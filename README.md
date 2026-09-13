# Flow

Flow est une PWA personnelle de pilotage financier orientee decision. Son objectif principal est de repondre a la question : combien puis-je reellement depenser aujourd'hui sans compromettre mes charges, mon epargne, mes objectifs et les prochains mois ?

## Stack

- FastAPI
- SQLite
- HTML/CSS/JavaScript natifs
- Docker Compose
- PWA mobile-first

## Structure

```text
flow-finance/
├── app/                  # application FastAPI et logique metier
├── tests/                # tests automatises
├── maintenance/          # outils de maintenance et mise a jour
├── docs/                 # documentation technique
├── data/                 # donnees runtime locales, non versionnees
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── CHANGELOG.md
└── README.md
```

## Donnees persistantes

La base SQLite est stockee hors de l'image Docker dans `./data/flow.db`. Le dossier `data/` ne doit jamais etre versionne.

## Deploiement Raspberry Pi

```bash
cd /home/pi/flow-finance
git pull origin main
docker compose up -d --build
docker compose ps
```

L'application ecoute sur le port `8010`.

## Verification

```bash
curl http://localhost:8010/api/health
docker compose logs --tail=100
```

## Regles de securite

- ne jamais versionner `.env` ;
- ne jamais versionner `data/` ou `flow.db` ;
- ne jamais supprimer/recreer la base sans sauvegarde explicite ;
- conserver les imports, historiques et sauvegardes hors du depot Git.
