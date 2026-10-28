## Gabarit inconnu, extracteur rules

60 factures. Exactitude par champ, en correspondance exacte après normalisation.

| Champ | Global | PDF natifs (42) | Scans (18) |
|---|---|---|---|
| Numéro de facture | 0,0 % | 0,0 % | 0,0 % |
| Date d'émission | 100,0 % | 100,0 % | 100,0 % |
| Échéance | 0,0 % | 0,0 % | 0,0 % |
| Nom du vendeur | 0,0 % | 0,0 % | 0,0 % |
| SIREN du vendeur | 98,3 % | 100,0 % | 94,4 % |
| TVA du vendeur | 100,0 % | 100,0 % | 100,0 % |
| Nom du client | 0,0 % | 0,0 % | 0,0 % |
| SIREN du client | 21,7 % | 23,8 % | 16,7 % |
| TVA du client | 46,7 % | 52,4 % | 33,3 % |
| Total HT | 0,0 % | 0,0 % | 0,0 % |
| Total TVA | 100,0 % | 100,0 % | 100,0 % |
| Total TTC | 0,0 % | 0,0 % | 0,0 % |
| IBAN | 100,0 % | 100,0 % | 100,0 % |
| Catégorie d'opération | 31,7 % | 35,7 % | 22,2 % |
| Lignes | 0,0 % | 0,0 % | 0,0 % |

**Factures extraites sans aucune erreur sur les 15 champs : 0,0 %**

### Détection des mentions obligatoires manquantes

| Anomalie | Précision | Rappel | Cas |
|---|---|---|---|
| SIREN du client absent | 21,7 % | 100,0 % | 13 |
| Catégorie d'opération absente | 31,7 % | 100,0 % | 19 |
| Pénalités de retard absentes | 100,0 % | 100,0 % | 6 |
| Indemnité de 40 € absente | 100,0 % | 100,0 % | 10 |
| Conditions d'escompte absentes | 100,0 % | 100,0 % | 19 |
| Numéro de facture mal formé | 100,0 % | 0,0 % | 3 |

### Routage et erreurs silencieuses

| Décision | Factures |
|---|---|
| À corriger | 0 |
| Revue humaine | 60 |
| Prête à émettre | 0 |

Factures avec au moins un champ essentiel faux **non envoyées en revue** (erreurs silencieuses) : **0** sur 60.

Factures avec un champ essentiel faux correctement envoyées en revue : 60.

### Latence (ms, CPU)

| Source | Médiane | p95 |
|---|---|---|
| PDF natifs | 39 | 53 |
| Scans | 2363 | 2595 |
