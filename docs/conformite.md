# Contrôles de conformité

Chaque anomalie produite par `facturia.validate` indique le champ EN 16931 concerné (BT ou BG) et, quand elle existe, la règle officielle. Les règles BR-FR sont celles du schematron français *Flux 2* distribué avec la bibliothèque `factur-x`. Les tests vérifient que le validateur de factur-ia et ce schematron signalent les mêmes manques. Le code technique de chaque anomalie, renvoyé par l'API, figure dans `validate.py`.

## Réforme 2026 et règles françaises

| Anomalie | Gravité | Champ | Règle officielle | Amende de 15 € |
|---|---|---|---|---|
| SIREN du client absent ou invalide | bloquante | BT-47 | BR-FR-11, et BR-FR-12 pour l'adresse électronique BT-49 | oui |
| Catégorie d'opération absente | bloquante | BT-23 | BR-FR-08, cadre de facturation B1, S1 ou M1 | oui |
| Adresse de livraison à vérifier | information | BG-15 | obligatoire si elle diffère de l'adresse de facturation | non |
| Option TVA sur les débits à vérifier | information | BT-8 | obligatoire si le vendeur a opté pour les débits | non |
| SIREN du vendeur absent ou invalide | bloquante | BT-30 | BR-FR-10 | oui |
| SIRET incohérent avec le SIREN | bloquante | BT-29 | BR-FR-09 | non |
| Numéro de facture mal formé | bloquante | BT-1 | BR-FR-01 et 02 : lettres, chiffres, plus, tiret, tiret bas et barre oblique, 35 caractères au plus | non |
| Année hors de 2000 à 2099 | bloquante | BT-2 | BR-FR-03 | non |
| Type de document non accepté | bloquante | BT-3 | BR-FR-04 | non |
| Taux de TVA non autorisé en France | bloquante | BT-119, BT-152 | BR-FR-16 | non |
| Pénalités de retard absentes | bloquante | BT-22 | BR-FR-05, note PMD, Code de commerce L441-9 | non |
| Indemnité de 40 € absente | bloquante | BT-22 | BR-FR-05, note PMT | non |
| Conditions d'escompte absentes | bloquante | BT-22 | BR-FR-05, note AAB | non |

Les mentions du Code de commerce relèvent d'une amende administrative distincte, non chiffrée ici.

### Client particulier

La facture électronique obligatoire et les mentions du Code de commerce (L441-9) ne concernent que les échanges entre professionnels. Quand le client n'a ni SIREN, ni SIRET, ni numéro de TVA, ni forme juridique, et que son nom s'écrit comme celui d'une personne (« DUPONT Marie », « Mme Dupont »), l'outil :

* ne réclame ni le SIREN du client, ni la catégorie d'opération, ni les mentions de pénalités, d'indemnité et d'escompte, et ne compte aucune amende pour elles.
* le signale par une alerte, à confirmer : si le client est en réalité une entreprise, il faut ajouter son SIREN.
* vérifie le XML selon la seule norme EN 16931, les règles BR-FR visant la facturation entre entreprises.

La détection reste prudente : « Marie Dupont », sans nom en capitales ni civilité, garde les règles B2B. Une mention manquante est ainsi signalée à tort plutôt que manquée en silence.

## EN 16931, le socle européen

| Anomalie | Champ | Règle |
|---|---|---|
| Numéro de facture absent | BT-1 | BR-02 |
| Date d'émission absente | BT-2 | BR-03 |
| Nom du vendeur absent | BT-27 | BR-06 |
| Nom du client absent | BT-44 | BR-07 |
| Totaux absents | BT-109, BT-110, BT-112 | BR-12, BR-13, BR-14 |
| Aucune ligne de facture | BG-25 | BR-16 |
| Numéro de TVA du vendeur absent | BT-31 | BR-S-02 |
| Somme des lignes différente du total HT | BT-106 | BR-CO-10 |
| TVA par taux différente du total de TVA | BT-110 | BR-CO-14 |
| HT plus TVA différent du TTC | BT-112 | BR-CO-15 |
| Montant de TVA incohérent avec le taux | BT-117 | BR-S-09 |

## Contrôles supplémentaires

* Clé du numéro de TVA incorrecte, calculée comme (12 + 3 × (SIREN mod 97)) mod 97.
* Numéro de TVA qui ne correspond pas au SIREN du vendeur.
* Clé du numéro de TVA du client incorrecte.
* IBAN invalide selon la clé mod 97.
* Quantité fois prix unitaire différent du montant d'une ligne.
* Échéance antérieure à la date d'émission, ou date d'émission dans le futur.
* Net à payer supérieur au total TTC.
* SIRET du vendeur mal formé (nombre de chiffres ou clé de Luhn). Il est signalé mais jamais recopié dans le XML.

## Choix de génération du XML

| Donnée | Emplacement dans le XML CII |
|---|---|
| Catégorie d'opération | `BusinessProcessSpecifiedDocumentContextParameter/ID`, valeur B1, S1 ou M1 |
| Traitement B2B domestique | note BAR, valeur B2B |
| Pénalités, indemnité de 40 €, escompte | notes PMD, PMT et AAB |
| SIREN et SIRET | `SpecifiedLegalOrganization/ID` (schéma 0002) et `GlobalID` (schéma 0009) |
| Adresse électronique de facturation | `URIUniversalCommunication/URIID` (schéma 0225), le SIREN par défaut comme dans l'annuaire |
| Option TVA sur les débits | `ApplicableTradeTax/DueDateTypeCode`, valeur 5 |
| Facture déjà réglée (solde inférieur au TTC) | `TotalPrepaidAmount` (BT-113), pour que BR-CO-16 reste vérifiée |

Ces correspondances suivent les spécifications externes françaises telles que les reflète le schematron BR-FR. Elles sont à confirmer avec la plateforme agréée retenue, car certaines exigent une adresse électronique BT-34 ou BT-49 différente du SIREN.
