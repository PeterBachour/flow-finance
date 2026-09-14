# Règles de contribution Flow Finance

1. Lire `docs/FILE_MAP.md` avant d'ouvrir d'autres fichiers.
2. Le dépôt `PeterBachour/flow-finance`, branche `main`, est la source de vérité du code.
3. Ne jamais modifier l'ancien dossier `flow-finance/` de `coaster-collection`.
4. Rechercher les symboles concernés avant de lire ou modifier des fichiers.
5. Faire le plus petit changement compatible avec la demande.
6. Réutiliser les moteurs, routes, composants et migrations existants.
7. Ne jamais supprimer, recréer ou remplacer `flow.db`.
8. Ne jamais versionner `.env`, `data/`, une base, un relevé, une fiche de paie, un export personnel ou un secret.
9. Les migrations de base sont additives, idempotentes et testées sur une base existante.
10. Les transferts internes, remboursements, épargne, investissements et consommation restent sémantiquement séparés.
11. Une simulation ne modifie jamais le ledger réel.
12. Une estimation ou prévision expose toujours sa confiance et ses hypothèses.
13. Toute correction financière exige une validation explicite.
14. Les scripts d'écriture fonctionnent en dry-run par défaut et exigent `--apply`.
15. Ajouter ou adapter des tests déterministes pour chaque règle financière modifiée.
16. Tester uniquement le périmètre impacté, puis exécuter les contrôles de release concernés.
17. Préserver FastAPI, SQLite, Docker Compose et le frontend JavaScript/CSS natif sauf décision d'architecture explicite.
18. Maintenir le fonctionnement mobile-first, la PWA et l'accessibilité.
19. Synchroniser version backend, interface, manifest, service worker et changelog lors d'une release.
20. Mettre à jour `CHANGELOG.md` et `app/static/changelog.json` uniquement pour une release.
21. Ne pas présenter un test comme réussi s'il n'a pas été exécuté.
22. Ne pas déployer sur le Raspberry Pi depuis GitHub sans validation explicite de l'état de la base et d'une sauvegarde.
