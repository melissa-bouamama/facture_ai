## in-distribution — extracteur `rules`

200 factures — exactitude par champ (correspondance exacte après normalisation)

| Champ | Global | native (n=139) | ocr (n=61) |
|---|---|---|---|
| `number` | 100.0% | 100.0% | 100.0% |
| `issue_date` | 100.0% | 100.0% | 100.0% |
| `due_date` | 100.0% | 100.0% | 100.0% |
| `seller.name` | 99.5% | 100.0% | 98.4% |
| `seller.siren` | 100.0% | 100.0% | 100.0% |
| `seller.vat_id` | 100.0% | 100.0% | 100.0% |
| `buyer.name` | 99.5% | 100.0% | 98.4% |
| `buyer.siren` | 100.0% | 100.0% | 100.0% |
| `buyer.vat_id` | 100.0% | 100.0% | 100.0% |
| `total_without_vat` | 100.0% | 100.0% | 100.0% |
| `total_vat` | 100.0% | 100.0% | 100.0% |
| `total_with_vat` | 100.0% | 100.0% | 100.0% |
| `iban` | 100.0% | 100.0% | 100.0% |
| `operation_category` | 100.0% | 100.0% | 100.0% |
| `lines` | 100.0% | 100.0% | 100.0% |

**Factures extraites sans aucune erreur sur les 15 champs : 99.0%**

### Détection des mentions obligatoires manquantes

| Anomalie | Précision | Rappel | Support |
|---|---|---|---|
| `FR-BUYER-SIREN-MISSING` | 100.0% | 100.0% | 50 |
| `FR-OPERATION-CATEGORY-MISSING` | 100.0% | 100.0% | 60 |
| `FR-NOTE-PENALTIES-MISSING` | 100.0% | 100.0% | 33 |
| `FR-NOTE-RECOVERY-FEE-MISSING` | 100.0% | 100.0% | 34 |
| `FR-NOTE-DISCOUNT-MISSING` | 100.0% | 100.0% | 57 |
| `FR-INVOICE-NUMBER-FORMAT` | 100.0% | 100.0% | 8 |

### Routage et erreurs silencieuses

| Décision | Factures |
|---|---|
| `fix_required` | 152 |
| `human_review` | 1 |
| `ready` | 47 |

- Factures avec au moins un champ essentiel faux **non envoyées en revue** (erreurs silencieuses) : **2** / 200
- Factures avec un champ essentiel faux correctement envoyées en revue : 0

### Latence (ms, CPU)

| Source | médiane | p95 |
|---|---|---|
| native | 37 | 61 |
| ocr | 2566 | 2822 |
