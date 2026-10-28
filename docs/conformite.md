# Contrôles de conformité

Chaque anomalie produite par `facturia.validate` indique le champ EN 16931 concerné (BT/BG) et, quand elle existe, la règle officielle. Les codes `BR-FR-*` sont ceux du schematron français *Flux 2* distribué avec la bibliothèque `factur-x` ; les tests vérifient que notre validateur et ce schematron signalent les mêmes manques.

## Réforme 2026 et règles françaises

| Code factur-ia | Gravité | Champ | Règle officielle | Amende 15 € |
|---|---|---|---|---|
| `FR-BUYER-SIREN-MISSING` / `-INVALID` | erreur | BT-47 | BR-FR-11 (et BR-FR-12 pour l'adresse électronique BT-49) | oui |
| `FR-OPERATION-CATEGORY-MISSING` | erreur | BT-23 | BR-FR-08 (cadre de facturation B1 / S1 / M1) | oui |
| `FR-DELIVERY-ADDRESS-CHECK` | info | BG-15 | mention obligatoire si l'adresse diffère | — |
| `FR-VAT-DEBITS-CHECK` | info | BT-8 | mention obligatoire si option pour les débits | — |
| `FR-SELLER-SIREN-MISSING` / `-INVALID` | erreur | BT-30 | BR-FR-10 | oui |
| `FR-SELLER-SIRET-INCOHERENT` | erreur | BT-29 | BR-FR-09 | — |
| `FR-INVOICE-NUMBER-FORMAT` | erreur | BT-1 | BR-FR-01/02 : `[A-Za-z0-9+-_/]`, 35 caractères max | — |
| `FR-DATE-YEAR` | erreur | BT-2 | BR-FR-03 | — |
| `FR-TYPE-CODE` | erreur | BT-3 | BR-FR-04 | — |
| `FR-VAT-RATE-INVALID` | erreur | BT-119/152 | BR-FR-16 (taux autorisés en France) | — |
| `FR-NOTE-PENALTIES-MISSING` | erreur | BT-22 | BR-FR-05 (note `PMD`), Code de commerce L441-9 | — |
| `FR-NOTE-RECOVERY-FEE-MISSING` | erreur | BT-22 | BR-FR-05 (note `PMT`, indemnité de 40 €) | — |
| `FR-NOTE-DISCOUNT-MISSING` | erreur | BT-22 | BR-FR-05 (note `AAB`) | — |

Les mentions du Code de commerce relèvent d'une amende administrative distincte, non chiffrée ici.

## EN 16931 (socle européen)

| Code factur-ia | Champ | Règle |
|---|---|---|
| `CORE-NUMBER-MISSING` | BT-1 | BR-02 |
| `CORE-ISSUE-DATE-MISSING` | BT-2 | BR-03 |
| `CORE-SELLER-NAME-MISSING` | BT-27 | BR-06 |
| `CORE-BUYER-NAME-MISSING` | BT-44 | BR-07 |
| `CORE-TOTALS-MISSING` | BT-109/110/112 | BR-12/13/14 |
| `CORE-NO-LINES` | BG-25 | BR-16 |
| `SELLER-VAT-MISSING` | BT-31 | BR-S-02 |
| `LINES-SUM-MISMATCH` | BT-106 | BR-CO-10 |
| `VAT-BREAKDOWN-MISMATCH` | BT-110 | BR-CO-14 |
| `TOTALS-UNBALANCED` | BT-112 | BR-CO-15 |
| `VAT-CALCULATION` | BT-117 | BR-S-09 |

## Contrôles supplémentaires

`SELLER-VAT-INVALID` (clé de TVA ≠ `(12 + 3 × (SIREN mod 97)) mod 97`), `SELLER-VAT-SIREN-MISMATCH`, `BUYER-VAT-INVALID`, `IBAN-INVALID` (mod 97), `LINE-ARITHMETIC` (qté × PU ≠ montant), `DUE-BEFORE-ISSUE`, `DATE-IN-FUTURE`, `AMOUNT-DUE-EXCEEDS-TOTAL`.

## Choix de génération du XML

| Donnée | Emplacement CII |
|---|---|
| Catégorie d'opération | `ExchangedDocumentContext/BusinessProcessSpecifiedDocumentContextParameter/ID` = `B1`, `S1` ou `M1` |
| Traitement B2B domestique | note `BAR` = `B2B` |
| Pénalités / indemnité 40 € / escompte | notes `PMD` / `PMT` / `AAB` |
| SIREN, SIRET | `SpecifiedLegalOrganization/ID@0002`, `GlobalID@0009` |
| Adresse électronique de facturation | `URIUniversalCommunication/URIID@0225` = SIREN (adresse par défaut de l'annuaire) |
| Option TVA sur les débits | `ApplicableTradeTax/DueDateTypeCode` = `5` |

Ces correspondances suivent les spécifications externes françaises telles que reflétées par le schematron BR-FR ; elles sont à confirmer avec la plateforme agréée retenue (certaines exigent une adresse électronique BT-34/BT-49 différente du SIREN).
