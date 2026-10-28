# Évaluation

## Protocole

Il n'existe pas de jeu public de factures françaises annotées (et pour cause : ce sont des données commerciales). Le benchmark repose donc sur un **générateur** (`facturia.synth`) qui produit des PDF réalistes et le JSON attendu :

- 4 gabarits (classique, moderne, compact, artisan), libellés synonymes tirés au hasard (« Total HT », « Montant HT », « Total hors taxes »…), dates et montants dans plusieurs formats, désignations sur deux lignes, plusieurs taux de TVA ;
- 30 % des factures dégradées en **scan** : rastérisation 200 dpi, rotation jusqu'à ±1,2°, bruit gaussien, flou, compression JPEG ;
- mentions obligatoires **omises volontairement** (SIREN client 25 %, catégorie d'opération 30 %, pénalités 15 %, indemnité 40 € 15 %, escompte 30 %) et numéros de facture invalides (8 %), pour mesurer la détection ;
- identifiants fictifs mais avec des clés de contrôle valides.

Deux jeux, graines fixes, régénérés par `python bench/run_benchmark.py` :

| Jeu | Factures | Rôle |
|---|---|---|
| `in-distribution` | 200 | Les 4 gabarits ayant servi à écrire les règles. Mesure la non-régression, **pas** la généralisation. |
| `hors-gabarit` | 60 | Un 5e gabarit au vocabulaire et à la disposition absents des règles (« Réf. », « À l'attention de », « Paiement au plus tard le », « Base HT », « Total à payer », vendeur à droite). Mesure la généralisation et, surtout, la capacité à **détecter ses propres échecs**. |

Une valeur est comptée juste si elle est **exactement** égale à la vérité terrain après normalisation (dates ISO, montants décimaux, accents et casse ignorés pour les textes). Pour les lignes, il faut le bon nombre de lignes et, pour chacune, la même désignation, quantité et montant.

Une **erreur silencieuse** est une facture dont au moins un champ essentiel (numéro, date, vendeur, SIREN vendeur, client, totaux, lignes) est faux **et** qui n'a pas été envoyée en revue humaine. C'est la métrique qui compte pour un outil comptable.

## Résultats — extracteur `rules`

Machine : 2 cœurs Intel Xeon 2,8 GHz, Python 3.13, sans GPU. Détails complets : [`bench/results/`](../bench/results/).

### In-distribution (200 factures, dont 61 scannées)

| Champ | Global | Natif (139) | Scanné (61) |
|---|---|---|---|
| numéro, dates, SIREN/TVA vendeur et client, totaux, IBAN, catégorie | 100 % | 100 % | 100 % |
| nom du vendeur | 99,5 % | 100 % | 98,4 % |
| nom du client | 99,5 % | 100 % | 98,4 % |
| lignes de facture | 100 % | 100 % | 100 % |
| **facture entièrement juste** | **99,0 %** | 100 % | 96,7 % |

Détection des mentions manquantes : précision et rappel de **100 %** sur les 6 anomalies suivies (SIREN client, catégorie d'opération, pénalités, indemnité de 40 €, escompte, format du numéro).

Routage : 47 `ready`, 152 `fix_required`, 1 `human_review`. **2 erreurs silencieuses** : deux noms d'entreprise mal lus par l'OCR (« I » lu « l ») avec une confiance encore suffisante.

### Hors gabarit (60 factures, dont 18 scannées)

| Champ | Exactitude |
|---|---|
| date d'émission, SIREN et TVA vendeur, total TVA, IBAN | 98 – 100 % |
| SIREN client, TVA client, catégorie d'opération | 22 %, 47 %, 32 % (justes uniquement quand la mention est absente) |
| numéro, échéance, noms, total HT, total TTC, lignes | 0 % |
| **facture entièrement juste** | **0 %** |

Les règles ne connaissent pas ce vocabulaire : elles échouent, comme attendu. Mais **les 60 factures sont envoyées en revue humaine (0 erreur silencieuse)** : les champs essentiels manquants ou peu sûrs et les incohérences arithmétiques font basculer la décision. C'est précisément le cas où le mode `hybrid` appelle le LLM.

### Latence

| | Médiane | p95 |
|---|---|---|
| PDF natif | 37 ms | 61 ms |
| PDF scanné (redressement + OCR 300 dpi) | 2,6 s | 2,8 s |

## Ce que ces chiffres ne disent pas

- **Biais de conception** : les règles ont été écrites et corrigées en observant le générateur in-distribution ; 99 % n'est pas une performance attendue sur de vraies factures. Le jeu hors gabarit donne une idée bien plus réaliste de ce qui arrive face à un fournisseur inconnu.
- **Scans simulés** : le bruit est plus régulier que celui d'un vrai scanner ou d'une photo de smartphone (ombres, perspective, papier froissé, tampons, écriture manuscrite).
- **LLM non mesuré ici** : l'environnement de développement n'avait pas accès à un modèle. Le mode `hybrid` est couvert par des tests avec un LLM simulé (escalade, fusion, ancrage, panne). Pour le mesurer sur un vrai modèle :

```bash
export FACTURIA_LLM_BASE_URL=http://localhost:11434/v1 FACTURIA_LLM_MODEL=qwen2.5:7b-instruct
python bench/run_benchmark.py --backend hybrid
```

## Évaluer sur ses propres factures

Placer dans un dossier des paires `facture.pdf` + `facture.json` (JSON au format du modèle `Invoice`, voir `examples/rapport_conforme.json` → clé `invoice`), éventuellement avec `"_spec": {"expected_issues": [...]}`, puis :

```bash
facturia evaluate mon_dossier --backend hybrid --out resultats.md
```
