SOURCE_REVISION = 'notion-finance-v1.8-2026-09-08-r5'
ROOT_SOURCE_ID = '3a32b5b7-a445-8187-9c09-fba0bbb7b1ca'
ROOT_SOURCE_URL = 'https://app.notion.com/p/3a32b5b7a44581879c09fba0bbb7b1ca'
REFERENCE_SOURCE_ID = '3a92b5b7-a445-81ac-9469-c08cd959a251'
REFERENCE_SOURCE_URL = 'https://app.notion.com/p/3a92b5b7a44581ac9469c08cd959a251'
HISTORY_SOURCE_URL = 'https://app.notion.com/p/689fd3c7b68042c9b4c48999869f2225'

ACCOUNTS = [
    {'key':'account:lcl-current','name':'Compte courant LCL','kind':'checking','balance':953.25,'as_of':'2026-09-07','wealth':1,'liquidity':1,'safe':1,'status':'confirmed','confidence':1.0},
    {'key':'account:joint','name':'Compte commun','kind':'joint','balance':2618.18,'as_of':'2026-07-26','wealth':1,'liquidity':1,'safe':0,'status':'confirmed','confidence':0.98},
    {'key':'account:livret-a','name':'Livret A','kind':'savings','balance':1150.00,'as_of':'2026-08-30','wealth':1,'liquidity':1,'safe':0,'status':'confirmed','confidence':1.0},
    {'key':'account:ldds','name':'LDDS','kind':'savings','balance':596.51,'as_of':'2026-08-30','wealth':1,'liquidity':1,'safe':0,'status':'confirmed','confidence':1.0},
    {'key':'account:boursobank','name':'Compte courant Boursobank','kind':'checking','balance':133.00,'as_of':'2026-08-30','wealth':1,'liquidity':1,'safe':0,'status':'confirmed','confidence':1.0},
    {'key':'account:lcl-vie','name':'LCL Vie','kind':'life_insurance','balance':2248.58,'as_of':'2026-07-26','wealth':1,'liquidity':0,'safe':0,'status':'confirmed','confidence':0.98},
]

BALANCE_HISTORY = [
    ('account:lcl-current','2026-07-26',50.66,'historical','reference-v1.2:lcl-before-salary'),
    ('account:lcl-current','2026-08-01',1401.00,'confirmed','reference-v1.3:lcl'),
    ('account:lcl-current','2026-08-30',50.66,'confirmed','review-v1.6:lcl'),
    ('account:lcl-current','2026-09-07',953.25,'confirmed','review-v1.8:lcl'),
    ('account:livret-a','2026-08-01',50.00,'confirmed','reference-v1.3:livret-a'),
    ('account:livret-a','2026-08-30',1150.00,'confirmed','review-v1.6:livret-a'),
    ('account:ldds','2026-08-01',76.51,'historical','review-v1.5:ldds'),
    ('account:ldds','2026-08-30',596.51,'confirmed','review-v1.6:ldds'),
    ('account:boursobank','2026-07-26',157.39,'historical','reference-v1.2:boursobank'),
    ('account:boursobank','2026-08-30',133.00,'confirmed','review-v1.6:boursobank'),
    ('account:lcl-vie','2026-07-26',2248.58,'confirmed','goal:lcl-vie:balance'),
    ('account:joint','2026-07-26',2618.18,'confirmed','review-v1.6:joint'),
]

MONTHLY_HISTORY = [
    {'key':'month:2026-02','month':'2026-02','salary':2926.61,'debits':4759.55,'credits':7207.51,'closing':2447.96,'fixed':2065.67,'variable':2293.88,'savings':400.00,'status':'confirmed','source_id':'3a32b5b7-a445-81bc-8597-ed8a5ff7457b','source_url':'https://app.notion.com/p/3a32b5b7a44581bc8597ed8a5ff7457b','comment':'Les crédits incluent virements internes et remboursements; dépenses variables estimées.'},
    {'key':'month:2026-03','month':'2026-03','salary':2931.61,'debits':5854.60,'credits':8977.36,'closing':3122.76,'fixed':1698.17,'variable':3956.43,'savings':200.00,'status':'confirmed','source_id':'3a32b5b7-a445-8164-b813-e5a53012cf54','source_url':'https://app.notion.com/p/3a32b5b7a4458164b813e5a53012cf54','comment':'Crédits gonflés par remboursements et virements internes.'},
    {'key':'month:2026-04','month':'2026-04','salary':2941.61,'debits':3093.38,'credits':6251.12,'closing':3157.74,'fixed':1682.68,'variable':1310.70,'savings':100.00,'status':'confirmed','source_id':'3a32b5b7-a445-81b4-83e8-eb036274f726','source_url':'https://app.notion.com/p/3a32b5b7a44581b483e8eb036274f726','comment':'Charges fixes comprenant notamment 1 400 € versés au compte commun.'},
    {'key':'month:2026-05','month':'2026-05','salary':2956.61,'debits':3514.62,'credits':6489.25,'closing':2974.63,'fixed':1735.69,'variable':1478.93,'savings':300.00,'status':'confirmed','source_id':'3a32b5b7-a445-8149-8530-dca71e60b262','source_url':'https://app.notion.com/p/3a32b5b7a44581498530dca71e60b262','comment':'Plusieurs dépenses exceptionnelles; épargne identifiée estimée à partir des virements libellés comme épargne.'},
    {'key':'month:2026-06','month':'2026-06','salary':None,'debits':3198.20,'credits':3256.53,'closing':58.33,'fixed':1761.25,'variable':1286.95,'savings':150.00,'status':'confirmed','source_id':'3a32b5b7-a445-817b-8b14-f67e4656b9d1','source_url':'https://app.notion.com/p/3a32b5b7a445817b8b14f67e4656b9d1','comment':'Le salaire de fin juin n est pas clairement identifiable; ne pas extrapoler.'},
]

CONFIRMED_TRANSACTIONS = [
    {'key':'tx:2026-07-31:darty:3125','account':'account:lcl-current','date':'2026-07-31','amount':-3125.00,'label':'Darty - paiement appartement','category':'Logement','type':'expense','transfer':0,'status':'confirmed'},
    {'key':'tx:2026-08-30:joint:1200','account':'account:lcl-current','destination':'account:joint','date':'2026-08-30','amount':-1200.00,'label':'Virement compte commun - préparation septembre','category':'Transfert interne','type':'transfer','transfer':1,'status':'confirmed'},
    {'key':'tx:2026-08-30:ldds:520','account':'account:lcl-current','destination':'account:ldds','date':'2026-08-30','amount':-520.00,'label':'Virement LDDS - préparation septembre','category':'Transfert interne','type':'transfer','transfer':1,'status':'confirmed'},
    {'key':'tx:2026-08-30:livret-a:100','account':'account:lcl-current','destination':'account:livret-a','date':'2026-08-30','amount':-100.00,'label':'Virement Livret A - préparation septembre','category':'Transfert interne','type':'transfer','transfer':1,'status':'confirmed'},
    {'key':'tx:2026-08-30:boursobank:100','account':'account:lcl-current','destination':'account:boursobank','date':'2026-08-30','amount':-100.00,'label':'Virement Boursobank - circuit LCL Vie et assurance','category':'Transfert interne','type':'transfer','transfer':1,'status':'confirmed'},
]

RECURRING = [
    {'key':'recurring:mortgage-interest','account':'account:lcl-current','label':'Prêt immobilier / intérêts','amount':-207.20,'day':10,'category':'Crédits','kind':'commitment','certainty':'expected'},
    {'key':'recurring:navigo','account':'account:lcl-current','label':'Navigo','amount':-90.80,'day':2,'category':'Transport','kind':'commitment','certainty':'expected'},
    {'key':'recurring:joint-from-sept','account':'account:lcl-current','label':'Compte commun','amount':-1200.00,'day':1,'category':'Transfert interne','kind':'transfer','certainty':'expected'},
]

RULES = [
    {'key':'rule:safety-reserve','type':'minimum_reserve','name':'Réserve minimale compte courant','cents':20000,'start':'2026-08-01','status':'active','comment':'Préserver au moins 200 € sur le compte courant; V1.7 priorise son rétablissement.'},
    {'key':'rule:salary-reference','type':'income_reference','name':'Salaire net mensuel de référence','cents':291661,'start':'2026-07-26','status':'active','comment':'Salaire de référence documentaire. Le jour exact n est pas inventé.'},
    {'key':'rule:salary-next-month','type':'income_allocation','name':'Le salaire reçu en fin de mois finance le mois suivant','text':'end_of_month_to_next_month','start':'2026-07-26','status':'active','comment':'Règle métier explicite du référentiel.'},
    {'key':'rule:boursobank-circuit','type':'account_routing','name':'Circuit Boursobank pour LCL Vie et assurance emprunteur','cents':12236,'start':'2026-07-26','status':'active','comment':'100 € LCL Vie + 22,36 € assurance emprunteur; ne pas traiter comme argent librement dépensable.'},
    {'key':'rule:chatgpt-reimbursed','type':'expense_treatment','name':'ChatGPT est un frais professionnel remboursé','cents':2299,'start':'2026-07-26','status':'active','comment':'Coût personnel net nul après remboursement.'},
    {'key':'rule:no-family-debt','type':'debt','name':'Dette envers les parents','cents':0,'start':'2026-07-26','status':'active','comment':'Aucune avance familiale remboursable; remboursements futurs 0 €.'},
    {'key':'rule:lcl-vie-monthly','type':'monthly_saving','name':'Versement LCL Vie','cents':10000,'start':'2026-07-26','status':'active','comment':'Versement obligatoire mensuel depuis Boursobank; jour exact non inventé.'},
    {'key':'rule:insurance-monthly','type':'monthly_expense','name':'Assurance emprunteur','cents':2236,'start':'2026-07-26','status':'active','comment':'Prélèvement mensuel depuis Boursobank; jour exact non inventé.'},
    {'key':'rule:phone-monthly','type':'monthly_expense','name':'Téléphone','cents':990,'start':'2026-07-26','status':'active','comment':'Charge mensuelle documentée; jour exact non figé par Notion.'},
    {'key':'rule:apple-monthly','type':'monthly_expense','name':'Apple','cents':1398,'start':'2026-07-26','status':'active','comment':'Charge mensuelle documentée.'},
    {'key':'rule:velib-monthly','type':'monthly_expense','name':'Vélib','cents':930,'start':'2026-07-26','status':'active','comment':'Charge mensuelle documentée.'},
    {'key':'rule:ldds-sep-dec','type':'monthly_saving','name':'Versement LDDS planifié septembre-décembre 2026','cents':51225,'start':'2026-09-01','end':'2026-12-31','status':'active','comment':'Plan V1.2; septembre a été exécuté à 520 € et ne doit pas être doublé.'},
    {'key':'rule:livret-sep-dec','type':'monthly_saving','name':'Versement Livret A planifié septembre-décembre 2026','cents':5000,'start':'2026-09-01','end':'2026-12-31','status':'active','comment':'Plan documentaire; septembre a été exécuté à 100 €.'},
    {'key':'rule:tax-sep-nov','type':'monthly_expense','name':'Solde impôt septembre-novembre 2026','cents':11300,'start':'2026-09-01','end':'2026-11-30','status':'active','comment':'Montant planifié, pas marqué comme payé sans confirmation.'},
    {'key':'rule:tax-dec','type':'monthly_expense','name':'Solde impôt décembre 2026','cents':11600,'start':'2026-12-01','end':'2026-12-31','status':'active','comment':'Montant planifié, pas marqué comme payé sans confirmation.'},
    {'key':'rule:variable-sep-dec','type':'spending_budget','name':'Dépenses variables de référence septembre-décembre 2026','cents':48000,'start':'2026-09-01','end':'2026-12-31','status':'active','comment':'Hypothèse budgétaire documentée; ne constitue pas une transaction.'},
    {'key':'rule:august-variable-cap','type':'spending_cap','name':'Plafond dépenses personnelles août 2026','cents':39600,'start':'2026-08-01','end':'2026-08-31','status':'inactive','comment':'Règle historique V1.3, expirée fin août.'},
]

GOALS = [
    {'key':'goal:apartment-march-2027','name':'Paiement appartement — Mars 2027','target':3150.00,'current':300.00,'monthly':475.00,'date':'2027-03-01','priority':10,'active':1,'source_id':'3a32b5b7-a445-81df-8c12-cf55309277ae','source_url':'https://app.notion.com/p/3a32b5b7a44581df8c12cf55309277ae'},
    {'key':'goal:lcl-vie','name':'LCL Vie long terme','target':5000.00,'current':2248.58,'monthly':100.00,'date':'2028-12-31','priority':10,'active':1,'source_id':'3a32b5b7-a445-811d-a64e-d887542ed704','source_url':'https://app.notion.com/p/3a32b5b7a445811da64ed887542ed704'},
    {'key':'goal:apartment-purchases-2027','name':'Achats appartement — Juillet 2027','target':5400.00,'current':0.00,'monthly':500.00,'date':'2027-07-01','priority':10,'active':1,'source_id':'3a32b5b7-a445-8100-9a4d-d6b038557278','source_url':'https://app.notion.com/p/3a32b5b7a44581009a4dd6b038557278'},
    {'key':'goal:emergency-fund','name':'Fonds d urgence','target':6000.00,'current':300.00,'monthly':150.00,'date':'2028-12-31','priority':10,'active':1,'source_id':'3a32b5b7-a445-8116-af6e-c76c140cfd6f','source_url':'https://app.notion.com/p/3a32b5b7a4458116af6ec76c140cfd6f'},
    {'key':'goal:loan-reduction-2027','name':'Réduction du prêt d août 2027','target':1500.00,'current':0.00,'monthly':0.00,'date':'2027-08-01','priority':50,'active':1,'source_id':'3a32b5b7-a445-81d9-b22b-f483ab74ce1e','source_url':'https://app.notion.com/p/3a32b5b7a44581d9b22bf483ab74ce1e'},
    {'key':'goal:apartment-july-2026-history','name':'Paiement appartement — Juillet 2026','target':3150.00,'current':3150.00,'monthly':0.00,'date':'2026-07-31','priority':10,'active':0,'source_id':'3a32b5b7-a445-81c3-ad8d-dfd1d378352f','source_url':'https://app.notion.com/p/3a32b5b7a44581c3ad8ddfd1d378352f'},
]

DECISIONS = [
    {'key':'decision:2026-07-26:no-family-debt','date':'2026-07-26','title':'Aucune dette familiale','details':'Aucune avance familiale remboursable de 500 €; dette et remboursement futurs à 0 €.','status':'active'},
    {'key':'decision:2026-08-01:darty-real','date':'2026-08-01','title':'Montant Darty réel retenu','details':'Le paiement réellement effectué le 31 juillet est 3 125 €, remplaçant l ancienne hypothèse à 3 150 €.','status':'active'},
    {'key':'decision:2026-08-30:september-prep','date':'2026-08-30','title':'Préparation financière septembre','details':'1 200 € compte commun, 520 € LDDS, 100 € Livret A et 100 € Boursobank déjà transférés.','status':'active'},
    {'key':'decision:2026-09-06:no-extrapolation','date':'2026-09-06','title':'Ne pas extrapoler les soldes','details':'Conserver les derniers soldes confirmés tant qu aucune donnée bancaire plus récente n est disponible.','status':'active'},
    {'key':'decision:2026-09-08:lcl-current','date':'2026-09-08','title':'Solde LCL courant actualisé','details':'Le solde LCL confirmé au 7 septembre est 953,25 €. Cette valeur remplace 50,66 € pour le pilotage courant.','status':'active'},
]
