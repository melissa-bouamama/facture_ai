## hors-gabarit — extracteur `rules`

60 factures — exactitude par champ (correspondance exacte après normalisation)

| Champ | Global | native (n=42) | ocr (n=18) |
|---|---|---|---|
| `number` | 0.0% | 0.0% | 0.0% |
| `issue_date` | 100.0% | 100.0% | 100.0% |
| `due_date` | 0.0% | 0.0% | 0.0% |
| `seller.name` | 0.0% | 0.0% | 0.0% |
| `seller.siren` | 98.3% | 100.0% | 94.4% |
| `seller.vat_id` | 100.0% | 100.0% | 100.0% |
| `buyer.name` | 0.0% | 0.0% | 0.0% |
| `buyer.siren` | 21.7% | 23.8% | 16.7% |
| `buyer.vat_id` | 46.7% | 52.4% | 33.3% |
| `total_without_vat` | 0.0% | 0.0% | 0.0% |
| `total_vat` | 100.0% | 100.0% | 100.0% |
| `total_with_vat` | 0.0% | 0.0% | 0.0% |
| `iban` | 100.0% | 100.0% | 100.0% |
| `operation_category` | 31.7% | 35.7% | 22.2% |
| `lines` | 0.0% | 0.0% | 0.0% |

**Factures extraites sans aucune erreur sur les 15 champs : 0.0%**

### Détection des mentions obligatoires manquantes

| Anomalie | Précision | Rappel | Support |
|---|---|---|---|
| `FR-BUYER-SIREN-MISSING` | 21.7% | 100.0% | 13 |
| `FR-OPERATION-CATEGORY-MISSING` | 31.7% | 100.0% | 19 |
| `FR-NOTE-PENALTIES-MISSING` | 100.0% | 100.0% | 6 |
| `FR-NOTE-RECOVERY-FEE-MISSING` | 100.0% | 100.0% | 10 |
| `FR-NOTE-DISCOUNT-MISSING` | 100.0% | 100.0% | 19 |
| `FR-INVOICE-NUMBER-FORMAT` | 100.0% | 0.0% | 3 |

### Routage et erreurs silencieuses

| Décision | Factures |
|---|---|
| `fix_required` | 0 |
| `human_review` | 60 |
| `ready` | 0 |

- Factures avec au moins un champ essentiel faux **non envoyées en revue** (erreurs silencieuses) : **0** / 60
- Factures avec un champ essentiel faux correctement envoyées en revue : 60

### Latence (ms, CPU)

| Source | médiane | p95 |
|---|---|---|
| native | 38 | 57 |
| ocr | 2434 | 2782 |
