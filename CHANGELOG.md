## 6.4.0 — Safe to Spend explicable

- Contrat d'explication réconcilié au centime.
- Sources, statuts et exclusions visibles par composante.
- Comparaison historique qualifiée sans invention de données.
- Interface mobile `Comprendre ce montant`.
- Lecture seule et ledger inchangé.

## 6.3.0 — Cockpit prédictif\n\n- Safe to Spend certifié dans le héros d'accueil.\n- Trajectoires engagée, réaliste et prudente jusqu'au prochain salaire.\n- Bande d'incertitude, seuil protégé et détail quotidien interactif.\n- Vues 7 jours et cycle, navigation tactile et clavier.\n- Blocage du montant lorsque le solde bancaire est obsolète.\n\n# Flow Finance — Changelog

## 6.2.0 — 2026-09-14
- Ajout d'une trajectoire quotidienne unifiée jusqu'à l'horizon du Safe to Spend.
- Trois scénarios alignés : engagé, réaliste et prudent.
- Zone d'incertitude issue des dépenses variables historiques, avec méthode et confiance exposées.
- Déduplication des échéances planifiées et récurrences correspondantes.
- La marge de sécurité reste une protection de solde et n'est jamais traitée comme une dépense.

## 6.1.0 — 2026-09-14
- Nouveau contrat certifié `GET /api/v6/safe-to-spend` fondé sur le moteur financier existant.
- Décomposition complète du solde, des échéances, récurrences, objectifs et marge de sécurité.
- Trois projections distinctes : engagée, réaliste et prudente.
- Point bas daté pour les événements confirmés, budget quotidien et confiance explicitée.
- Aucun montant disponible n'est exposé lorsque le solde est absent ou obsolète.

## 6.0.0 — 2026-09-14
- Ajout d'un référentiel documentaire unifié en lecture seule pour les relevés, fiches de paie et transactions importées.
- Nouvelle matrice mensuelle complète / à revoir / partielle / manquante sur une fenêtre configurable.
- Traçabilité transaction vers relevé, identité documentaire, empreinte de ligne et payload brut.
- Nouveaux endpoints `GET /api/v6/documentary-evidence` et `GET /api/v6/transactions/{id}/evidence`.
- Aucun document personnel n'est stocké dans Git ni répliqué par la nouvelle API.

## 5.7.0 — 2026-09-12
- Ajout du Data Quality Action Center dans le parcours Mouvements.
- Priorisation déterministe des relevés récents manquants, relevés à revoir, doublons puis fiches de paie manquantes.
- Chaque action expose sa preuve, le document attendu, son impact et les analyses débloquées après correction.
- Navigation directe vers l'import ou la revue concernée, sans correction financière automatique.
- Synchronisation du backend, du runtime principal, du manifest, des assets et du cache PWA en 5.7.0.

## 5.6.0 — 2026-09-12
- Ajout du History Readiness Gate pour mesurer si l'historique peut alimenter tendances, revenus et prévisions.
- Score de fiabilité sur 100 et contrôle renforcé des six derniers mois.
- Identification des bloqueurs et de la prochaine action de remédiation sans modification des données financières.

## 5.5.0 — 2026-09-12
- Ajout d'une vue de couverture historique configurable, sur 24 mois par défaut, pour les relevés bancaires et fiches de paie.
- Identification explicite des mois manquants, périodes complètes, relevés à revoir et doublons potentiels.
- Intégration de l'import multi-documents PDF/CSV dans le parcours Mouvements avec staging sans écriture avant validation explicite.
- Ajout de `GET /api/v5.5/history-coverage` et de `maintenance/audit_history_coverage.py` en lecture seule.
- Synchronisation du backend, du runtime principal, du manifest et du cache PWA en 5.5.0.

## 5.4.0 — 2026-09-12
- Synchronisation des revues d'import avec les catégorisations explicites et fermeture automatique des lignes réellement traitées.
- Promotion d'un relevé en `verified` uniquement lorsque sa revue est terminée et que l'équation comptable reste cohérente.
- Ajout d'un outil de rapprochement des revues d'import en dry-run par défaut.
- Durcissement de la mise à jour : l'image Docker construite est testée avant tout redémarrage du runtime.
- Audit financier quotidien strictement en lecture seule, avec échec uniquement sur les anomalies financières dures.
- Version applicative, cache PWA et assets frontend synchronisés en 5.4.0.

## 5.3.0 — 2026-09-11
- Snapshot financier unique partagé par l'Accueil, le centre de décision et le pilotage prédictif.
- Calcul du cockpit, du plan et des recommandations exécuté une seule fois par requête.
- Suppression des appels frontend redondants et invalidation coordonnée après une décision.
- Contrat V5.3 strictement en lecture seule, sans modification automatique des données financières.
- Release validée par 103 tests.

Ce fichier miroir le changelog embarqué dans l'application (`app/static/changelog.json`). Le changelog visible dans Flow est enrichi à l'exécution avec la release courante lorsque nécessaire.

## 4.2.0 — 2026-09-10
- Audit comptable des relevés importés avec contrôle `solde d'ouverture + crédits - débits = solde de clôture`.
- Vérification de la présence des snapshots bancaires de clôture et détection des écarts entre relevé et ledger importé.
- Séparation stricte des transferts internes, remboursements, épargne, dépenses exceptionnelles et consommation.
- Nouvelle carte `Pourquoi ce montant ?` reconstruisant le Safe to Spend composant par composant.
- Vue des dépenses de consommation sur les six derniers mois et compteur d'anomalies de données.
- Ajout de `maintenance/audit_financial_integrity.py` pour auditer directement la base SQLite du Raspberry Pi.

## 4.1.2 — 2026-09-10
- Fiabilisation du mois courant lorsque l'historique de transactions n'est pas encore suffisant : mode `balance-only` explicite à partir du dernier solde confirmé et des échéances connues.
- Exposition du mode de calcul et de son niveau de confiance dans l'interface pour éviter de présenter une estimation comme une donnée observée.
- Ajout d'un backfill idempotent des snapshots de solde manquants à partir des relevés bancaires déjà validés dans les imports.
- Alignement de la documentation, de la version applicative, du changelog embarqué et du cache PWA.

## 4.1.0 — 2026-09-10
- Parcours principal recentré sur quatre espaces : Accueil, Mois, Mouvements et Patrimoine.
- Accueil réorganisé autour du montant disponible aujourd'hui, du prochain décaissement et de la décision prioritaire.
- Hiérarchie visuelle, navigation, cartes, listes, formulaires et états responsive entièrement revus.
- Écran Mois restructuré autour du solde mensuel, du reste pilotable et des enveloppes adaptatives.
- Mouvements et Patrimoine simplifiés pour accélérer la recherche, la correction et la lecture de la trajectoire.
- Routines, décisions secondaires, apparence, diagnostic et mises à jour regroupés dans Réglages.

## 4.0.0 — 2026-09-09
- Frontend consolidé autour d'un seul runtime `v4-ui.js` et d'un seul design system `app.css`.
- Les modules frontend V3.1 à V3.6 ne sont plus chargés par l'application.
- Accueil, Mois, Mouvements, Patrimoine et Plus réunissent les moteurs décisionnels V3 dans une architecture cohérente.
- Data Intelligence V3.7 et stratégie financière V3.8 intégrées directement aux parcours V4.
- PWA V4 avec cache unique, contrôle de version 4.0.0 et service worker sans dépendance aux anciennes couches UI.

## 3.8.0 — 2026-09-09
- Allocation déterministe : réserve, objectifs obligatoires, autres objectifs puis surplus non affecté.
- Prise en compte de la marge minimale du forecast avant de proposer une capacité disponible.
- Surplus stratégique affiché sans exécution d'investissement ni choix automatique d'instrument financier.
- Méthode et ordre de priorité affichés explicitement.

## 3.7.0 — 2026-09-09
- Score de qualité basé sur catégorisation, exclusions, qualité de source et anomalies.
- Détection de dépenses atypiques et mouvements à faible confiance.
- Normalisation de marchands avec suggestions et alias confirmables explicitement.
- Aucune modification silencieuse des transactions à partir des suggestions de données.

## 3.6.0 — 2026-09-09
- Ouverture mensuelle et clôture du mois précédent déclenchées de manière idempotente depuis l'application.
- Rapprochement automatique des échéances planifiées avec les mouvements réels uniquement lorsque la confiance est élevée et non ambiguë.
- Decision Inbox consolidant imports à revoir, récurrences détectées, échéances non rapprochées, soldes obsolètes et objectifs à risque.
- Validation explicite obligatoire avant toute création de récurrence détectée.
- Routine financière quotidienne et suivi persistant des décisions sans création silencieuse de transaction bancaire.

## 3.5.0 — 2026-09-09
- Budget restant recalculé à partir des dépenses réelles et de la marge Safe to Spend.
- Redistribution uniquement des catégories en mode limite, sans toucher aux montants réservés.
- Reste conseillé et budget quotidien par catégorie jusqu'à la fin du mois.
- Clôture analytique avec écart budget/réel, taux d'épargne et catégories dépassées.
- Aucune modification automatique des budgets ni création de transaction.

## 3.4.0 — 2026-09-09
- Plan du mois généré à partir du forecast, des objectifs, des soldes et des règles de protection.
- Priorisation des risques de liquidité, sorties prévues, objectifs sous-financés et soldes à actualiser.
- Montants proposés explicables sans création automatique de transaction ni déplacement d'argent.
- Actions marquables comme faites, ignorées ou rouvertes avec état persistant.
- Journalisation des changements de statut dans l'Activity Log.

## 3.3.0 — 2026-09-09
- Projection déterministe des objectifs selon montant actuel, contribution mensuelle et date cible.
- Écart projeté, effort mensuel requis et signal de liquidité pour chaque objectif.
- Projection du patrimoine net sur 6 ou 12 mois à partir de la trajectoire de liquidité.
- Application d'un scénario V3.2 aux objectifs et au patrimoine.
- Hypothèses de projection explicites pour distinguer trajectoire calculée et valorisation future réelle.

## 3.2.0 — 2026-09-09
- Prévision financière explicite sur 3, 6 ou 12 mois.
- Clôture, point bas, entrées, sorties et marge sécurisée calculés mois par mois.
- Scénarios persistants séparés des données réelles.
- Hypothèses ponctuelles ou mensuelles avec comparaison baseline/scénario.
- Impact consolidé sur la clôture, le point bas et la marge minimale sans création de transaction réelle.

## 3.1.0 — 2026-09-09
- Édition directe des mouvements : libellé, catégorie, transfert, exceptionnel et exclusion analytique.
- Création d'une règle de catégorisation depuis un mouvement avec application rétroactive optionnelle.
- Filtres qualité pour mouvements non catégorisés, transferts non liés, exceptionnels et exclus.
- Centre de notifications financières : Safe to Spend, grosses sorties, soldes obsolètes et imports à revoir.
- Préférences de notifications persistantes et Activity Log enrichi.

## 3.0.1 — 2026-09-09
- Validation syntaxique de tout le backend avant qu'une mise à jour soit proposée.
- Compilation Python obligatoire pendant le build Docker.
- Healthcheck Docker et smoke tests sur `/api/health`, `/api/version` et `/api/v3/system`.
- Validation de l'image construite avant redémarrage du service actif.
- Rollback automatique vers l'image précédente si la nouvelle version échoue au runtime.

## 3.0.0 — 2026-09-09
- Nouveau shell applicatif unique et design system consolidé.
- Suppression du chargement frontend des couches historiques v14/v21/v22/v23/v24.
- Financial Health Score, alertes, Activity Log, System Center, feature flags et changelog intégrés.
- Recherche globale et centre d'ingestion conservés dans la nouvelle architecture.
- PWA renforcée : cache unique V3, contrôle de version frontend/backend et rechargement contrôlé.

## 2.7.0 — 2026-09-09
- Consolidation UI préparatoire à V3.

## 2.6.0 — 2026-09-09
- System Center et diagnostics centralisés.

## 2.5.0 — 2026-09-09
- Financial Health Score, alertes et Activity Log.

## 2.4.1 — 2026-09-09
- Changelog intégré et durcissement PWA.

## 2.4.0 — 2026-09-09
- Recherche globale et imports intelligents.

## 2.3.0 — 2026-09-09
- Simulation et prévision avancée.

## 2.2.0 — 2026-09-09
- Patrimoine et objectifs.

## 2.1.0 — 2026-09-09
- Decision Cockpit.

## 2.0.1 — 2026-09-09
- Correctifs responsive et cache PWA.

## 2.0.0 — 2026-09-09
- Fondations V2.
