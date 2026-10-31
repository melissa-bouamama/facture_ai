# Évaluation

## Protocole

Il n'existe pas de jeu public de factures françaises annotées, et pour cause : ce sont des données commerciales. Le benchmark repose donc sur un **générateur** (`facturia.synth`) qui produit des PDF réalistes et le JSON attendu.

* 4 gabarits (classique, moderne, compact, artisan), des libellés synonymes tirés au hasard (« Total HT », « Montant HT », « Total hors taxes »), des dates et des montants dans plusieurs formats, des désignations sur deux lignes et plusieurs taux de TVA.
* 30 % des factures dégradées en **scan** : rastérisation à 200 dpi, rotation jusqu'à 1,2° dans les deux sens, bruit gaussien, flou et compression JPEG.
* Des mentions obligatoires **omises volontairement** pour mesurer leur détection : SIREN du client (25 %), catégorie d'opération (30 %), pénalités (15 %), indemnité de 40 € (15 %), escompte (30 %), ainsi que des numéros de facture invalides (8 %).
* Des identifiants fictifs, avec des clés de contrôle valides.

Deux jeux à graine fixe, régénérés par `python bench/benchmark.py` :

| Jeu | Factures | Rôle |
|---|---|---|
| Gabarits connus | 200 | Les 4 gabarits ayant servi à écrire les règles. Mesure la non régression, **pas** la généralisation. |
| Gabarit inconnu | 60 | Un cinquième gabarit dont le vocabulaire et la disposition sont absents des règles (« Réf. », « À l'attention de », « Paiement au plus tard le », « Base HT », « Total à payer », vendeur à droite). Mesure la généralisation et surtout la capacité à **détecter ses propres échecs**. |

Une valeur est comptée juste si elle est **exactement** égale à la vérité terrain après normalisation : dates au format ISO, montants décimaux, accents et casse ignorés pour les textes. Pour les lignes, il faut le bon nombre de lignes et, pour chacune, la même désignation, la même quantité et le même montant.

Une **erreur silencieuse** est une facture dont au moins un champ essentiel (numéro, date, vendeur, SIREN du vendeur, client, totaux, lignes) est faux **et** qui n'a pas été envoyée en revue humaine. C'est la métrique qui compte pour un outil comptable.

## Résultats de l'extracteur à règles

Les chiffres de cette section ont été mesurés avec le moteur OCR Tesseract. La comparaison avec docTR suit.

Machine : 2 cœurs Intel Xeon à 2,8 GHz, Python 3.13, sans GPU. Résultats complets dans [`bench/results/rules`](../bench/results/rules/).

### Gabarits connus : 200 factures, dont 61 scannées

| Champ | Global | PDF natifs (139) | Scans (61) |
|---|---|---|---|
| Numéro, dates, SIREN et TVA du vendeur et du client, totaux, IBAN, catégorie | 100 % | 100 % | 100 % |
| Nom du vendeur | 99,5 % | 100 % | 98,4 % |
| Nom du client | 99,5 % | 100 % | 98,4 % |
| Lignes de facture | 100 % | 100 % | 100 % |
| **Facture entièrement juste** | **99,0 %** | 100 % | 96,7 % |

Détection des mentions manquantes : précision et rappel de **100 %** sur les 6 anomalies suivies (SIREN du client, catégorie d'opération, pénalités, indemnité de 40 €, escompte, format du numéro).

Routage : 47 factures prêtes à émettre, 152 à corriger, 1 en revue humaine. **2 erreurs silencieuses** : deux noms d'entreprise mal lus par l'OCR (« I » lu « l ») avec une confiance encore suffisante.

### Gabarit inconnu : 60 factures, dont 18 scannées

| Champ | Exactitude |
|---|---|
| Date d'émission, SIREN et TVA du vendeur, total TVA, IBAN | de 98 à 100 % |
| SIREN du client, TVA du client, catégorie d'opération | 22 %, 47 % et 32 %, justes seulement quand la mention est absente |
| Numéro, échéance, noms, total HT, total TTC, lignes | 0 % |
| **Facture entièrement juste** | **0 %** |

Les règles ne connaissent pas ce vocabulaire et échouent, comme prévu. Mais **les 60 factures sont envoyées en revue humaine, sans aucune erreur silencieuse** : les champs essentiels absents ou peu sûrs et les montants incohérents font basculer la décision. C'est précisément le cas où le moteur hybride appelle le LLM.

### Latence

| | Médiane | p95 |
|---|---|---|
| PDF natif | 40 ms | 66 ms |
| Scan, avec redressement et OCR à 300 dpi | 2,6 s | 3,1 s |

## Tesseract ou docTR : comparaison des moteurs OCR

Les 61 scans des gabarits connus, lus par chaque moteur puis traités par le même extracteur à règles.

| Moteur | Factures entièrement justes | Sans compter la ponctuation des désignations | Erreurs silencieuses | Envoyées en revue | Médiane par scan |
|---|---|---|---|---|---|
| Tesseract 5 (fra) | **96,7 %** | 96,7 % | **2** | 0 | 2,6 s |
| docTR léger (`db_mobilenet_v3_large`, `crnn_mobilenet_v3_small`) | 45,9 % | 73,8 % | 13 | 32 | 2,3 s |

Les montants, quantités et identifiants sont lus aussi bien par les deux moteurs. docTR perd en revanche les tirets isolés (« Formation Python - 2 jours » devient « Formation Python 2 jours »), ajoute des points parasites issus du bruit du scan, et ne peut pas écrire « œ », absent de son vocabulaire français (« main d'œuvre » devient « main d'ceuvre »). Les désignations comptant comme un champ essentiel, ces écarts deviennent des erreurs silencieuses.

Sur une vraie facture d'hébergement scannée, les deux moteurs extraient les mêmes valeurs. docTR y obtient une meilleure confiance, car Tesseract colle un mot parasite au libellé de la date d'émission, ce qui envoie la facture en revue.

Tesseract reste donc le moteur le plus fiable sur ce benchmark. docTR a l'avantage de s'installer entièrement en Python, sans binaire système.

## Ce que ces chiffres ne disent pas

* **Biais de conception** : les règles ont été écrites et corrigées en observant les gabarits connus. 99 % n'est pas une performance attendue sur de vraies factures. Le gabarit inconnu donne une idée bien plus réaliste de ce qui arrive face à un nouveau fournisseur.
* **Scans simulés** : le bruit est plus régulier que celui d'un vrai scanner ou d'une photo de téléphone (ombres, perspective, papier froissé, tampons, écriture manuscrite).
* **LLM non mesuré ici** : l'environnement de développement n'avait pas accès à un modèle. Le moteur hybride est couvert par des tests avec un LLM simulé (escalade, fusion, ancrage, panne). Pour le mesurer sur un vrai modèle :

```bash
export FACTURIA_LLM_BASE_URL=http://localhost:11434/v1 FACTURIA_LLM_MODEL=qwen2.5:7b-instruct
python bench/benchmark.py --backend hybrid
```

## Évaluer sur ses propres factures

Placez dans un dossier des paires `facture.pdf` et `facture.json`. Le JSON suit le modèle `Invoice` (voir la clé `invoice` de `examples/conforme.rapport.json`) et peut lister les anomalies attendues. Lancez ensuite :

```bash
facturia evaluate dossier --backend hybrid --out resultats.md
```
