## Gabarits connus, extracteur rules

200 factures. Exactitude par champ, en correspondance exacte après normalisation.

| Champ | Global | PDF natifs (139) | Scans (61) |
|---|---|---|---|
| Numéro de facture | 100,0 % | 100,0 % | 100,0 % |
| Date d'émission | 100,0 % | 100,0 % | 100,0 % |
| Échéance | 100,0 % | 100,0 % | 100,0 % |
| Nom du vendeur | 99,5 % | 100,0 % | 98,4 % |
| SIREN du vendeur | 100,0 % | 100,0 % | 100,0 % |
| TVA du vendeur | 100,0 % | 100,0 % | 100,0 % |
| Nom du client | 99,5 % | 100,0 % | 98,4 % |
| SIREN du client | 100,0 % | 100,0 % | 100,0 % |
| TVA du client | 100,0 % | 100,0 % | 100,0 % |
| Total HT | 100,0 % | 100,0 % | 100,0 % |
| Total TVA | 100,0 % | 100,0 % | 100,0 % |
| Total TTC | 100,0 % | 100,0 % | 100,0 % |
| IBAN | 100,0 % | 100,0 % | 100,0 % |
| Catégorie d'opération | 100,0 % | 100,0 % | 100,0 % |
| Lignes | 100,0 % | 100,0 % | 100,0 % |

**Factures extraites sans aucune erreur sur les 15 champs : 99,0 %**

### Détection des mentions obligatoires manquantes

| Anomalie | Précision | Rappel | Cas |
|---|---|---|---|
| SIREN du client absent | 100,0 % | 100,0 % | 50 |
| Catégorie d'opération absente | 100,0 % | 100,0 % | 60 |
| Pénalités de retard absentes | 100,0 % | 100,0 % | 33 |
| Indemnité de 40 € absente | 100,0 % | 100,0 % | 34 |
| Conditions d'escompte absentes | 100,0 % | 100,0 % | 57 |
| Numéro de facture mal formé | 100,0 % | 100,0 % | 8 |

### Routage et erreurs silencieuses

| Décision | Factures |
|---|---|
| À corriger | 152 |
| Revue humaine | 1 |
| Prête à émettre | 47 |

Factures avec au moins un champ essentiel faux **non envoyées en revue** (erreurs silencieuses) : **2** sur 200.

Factures avec un champ essentiel faux correctement envoyées en revue : 0.

### Latence (ms, CPU)

| Source | Médiane | p95 |
|---|---|---|
| PDF natifs | 40 | 66 |
| Scans | 2566 | 3063 |
