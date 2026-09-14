# Flow Finance V1.0

## Source de vérité

La base SQLite locale de Flow est la source de vérité opérationnelle. Notion est une source documentaire et historique utilisée par le moteur de migration, pas une dépendance nécessaire aux calculs quotidiens.

## Données réelles

- comptes financiers réels normalisés ;
- soldes courants datés ;
- historique de soldes ;
- historique mensuel financier ;
- transactions confirmées ;
- transferts internes ;
- objectifs ;
- règles financières ;
- décisions historiques ;
- provenance et niveau de confiance ;
- conflits de rapprochement conservés pour vérification.

## Moteur financier

- le Disponible sans risque utilise uniquement les comptes explicitement marqués comme dépensables ;
- Boursobank, épargne et placements ne gonflent pas le Disponible réel ;
- la réserve minimale documentée est appliquée au calcul ;
- les engagements datés et les obligations mensuelles sans date certaine sont distingués ;
- les virements déjà réalisés en préparation du mois suivant ne sont pas réservés une deuxième fois ;
- les charges LCL Vie et assurance déjà couvertes par Boursobank ne sont pas réservées une deuxième fois sur le compte courant ;
- les transferts internes sont exclus des dépenses patrimoniales ;
- le salaire de référence peut être utilisé sans inventer sa date exacte ;
- la règle selon laquelle le salaire reçu en fin de mois finance le mois suivant est conservée ;
- les valeurs Flow plus récentes ont priorité sur les anciens snapshots Notion lors d'une resynchronisation.

## Interface

- Accueil branché sur le moteur financier réel ;
- explication détaillée du Disponible sans risque ;
- préparation du mois suivant enrichie par les règles financières ;
- comptes et dates des derniers soldes visibles ;
- objectifs avec progression issue des données migrées ;
- historique financier dans Patrimoine ;
- règles financières actives dans Patrimoine ;
- décisions financières historiques dans Patrimoine ;
- Réglages > Données · Notion avec analyse, import, synchronisation, statistiques et conflits ;
- mise à jour applicative conservée ;
- cache PWA `flow-v1.0.0`.

## Migration et sécurité des données

La migration est additive et idempotente. Les comptes ou données Flow préexistants ne sont pas supprimés. Un solde Flow dont la date est plus récente qu'un snapshot Notion reste prioritaire. Une ambiguïté non résoluble automatiquement génère un conflit au lieu d'un écrasement silencieux.

## Tests ajoutés

- idempotence de la migration Notion ;
- absence de doublons de transactions importées ;
- non-double-comptage des transferts ;
- utilisation exclusive des comptes dépensables pour le Disponible réel ;
- couverture Boursobank de LCL Vie et assurance ;
- reconnaissance du préfinancement LDDS/Livret A du mois suivant ;
- priorité d'un solde Flow plus récent sur Notion ;
- réserve minimale de 200 €.

Les tests sont présents dans le dépôt. Aucun statut CI n'est actuellement publié par GitHub pour ces commits, donc leur exécution automatisée n'est pas attestée par le dépôt.
