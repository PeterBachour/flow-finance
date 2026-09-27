# Sauvegardes de la base Flow

La base SQLite contient les mouvements, comptes, objectifs et historiques locaux de Flow. Le script `maintenance/backup_flow_database.py` crée une copie cohérente sans arrêter le service, avec l'API de sauvegarde en ligne de SQLite.

Par défaut, la source est `data/flow.db` et les sauvegardes sont écrites dans le dossier voisin `../flow-finance-backups/`, hors du dépôt Git. Les fichiers sont créés avec des permissions privées et ne sont jamais ajoutés ou envoyés vers GitHub.

## Prévisualiser

Sans `--apply`, le script vérifie la base source et affiche le chemin qui serait utilisé. Il n'écrit aucun fichier :

```bash
cd /home/pi/flow-finance
python3 maintenance/backup_flow_database.py
```

## Créer une sauvegarde

L'option `--apply` est obligatoire pour écrire :

```bash
python3 maintenance/backup_flow_database.py --apply
```

Le script crée un nouveau fichier horodaté, vérifie `PRAGMA integrity_check`, puis publie le fichier final de façon atomique. Il ne remplace pas la base active et ne supprime aucune ancienne sauvegarde.

Pour choisir un autre emplacement :

```bash
python3 maintenance/backup_flow_database.py \
  --db /home/pi/flow-finance/data/flow.db \
  --backup-dir /home/pi/flow-finance-backups \
  --apply
```

Le message de réussite indique le chemin, la taille et le résultat d'intégrité, sans afficher de soldes ou de mouvements.

## Vérifier une copie

```bash
python3 -c "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute('PRAGMA integrity_check').fetchone()[0]); db.close()" \
  /home/pi/flow-finance-backups/NOM_DU_FICHIER.db
```

Conserve les sauvegardes sur un support distinct du Raspberry Pi pour te protéger aussi contre la panne ou la perte de l'appareil. Une restauration doit être faite manuellement après arrêt de Flow et vérification de la copie; le script ne restaure jamais automatiquement la base.
