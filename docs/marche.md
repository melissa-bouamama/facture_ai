# Le problème : la facture PDF devient illégale, mais elle est partout

## Ce qui change avec la réforme de la facturation électronique

| Date | Obligation |
|---|---|
| **1er septembre 2026** | Toutes les entreprises assujetties à la TVA doivent **recevoir** leurs factures B2B sous forme électronique, par une plateforme agréée. Les grandes entreprises et les ETI doivent aussi les **émettre**. |
| **1er septembre 2027** | Les **PME, TPE et micro-entreprises** doivent à leur tour **émettre** des factures électroniques et transmettre leurs données de transaction (e-reporting). |

Sources : [Previssima](https://www.previssima.fr/actualite/facturation-electronique-ce-qui-change-pour-les-entreprises-des-le-1er-septembre-2026.html), [LégiFiscal](https://www.legifiscal.fr/actualites-fiscales/4687-facturation-electronique-mois-lancement-3-entreprises-4-designe-plateforme.html).

Une facture électronique au sens de la réforme n'est **pas** un PDF envoyé par courriel. C'est un format **structuré** (UBL, CII) ou **hybride** (Factur-X, un PDF lisible qui embarque un XML exploitable par une machine), transmis par une plateforme agréée ([mon-expert-en-gestion](https://www.mon-expert-en-gestion.com/?p=1615)). Les TPE et PME peuvent encore émettre des PDF jusqu'au 1er septembre 2027, plus ensuite.

La loi de finances pour 2026 (article 123) a acté l'abandon du portail public au profit des plateformes privées et **renforcé les sanctions** ([KPMG Avocats](https://kpmg.com/av/fr/avocats/eclairages/2026/03/facturation-electronique-amenagement-des-obligations-et-renforcement-des-sanctions.html)).

### Quatre nouvelles mentions obligatoires

1. Le **SIREN du client**.
2. L'**adresse de livraison** des biens, si elle diffère de l'adresse de facturation.
3. La **catégorie d'opération** : livraison de biens, prestation de services ou opération mixte.
4. L'**option pour le paiement de la TVA d'après les débits**, le cas échéant.

### Ce que coûte une erreur

* **15 € par mention manquante ou inexacte** (CGI, article 1737 II), dans la limite de 25 % du montant de la facture.
* **50 € par facture** non émise au format électronique, dans la limite de 15 000 € par an.
* Surtout, une plateforme agréée **rejette** une facture dont une donnée obligatoire manque dans le XML. Il s'ensuit des litiges, des relances et des retards de paiement.

Source : [ma-facture-electronique.org](https://ma-facture-electronique.org/reforme-2026/nouvelles-mentions-obligatoires/siren-client/).

## L'état du terrain

* **Avant la réforme**, 58 % des entreprises concernées utilisaient le PDF, 43 % envoyaient encore du papier et **83 % n'utilisaient aucun des formats requis**. Enquête OpinionWay pour Quadient auprès de 364 décideurs, 2024 ([Solutions Numériques](https://www.solutions-numeriques.com/facturation-electronique-obligatoire-en-2026-ou-en-sont-les-entreprises/)).
* **En février 2026**, 38 % des entreprises n'avaient engagé aucune action concrète et 40 % ne connaissaient pas de plateforme agréée. Enquête OpinionWay pour l'Ordre des experts comptables ([LégiFiscal](https://www.legifiscal.fr/actualites-fiscales/4560-facturation-electronique-38-entreprises-ne-sont-pretes.html)).
* **En juin 2026**, 26 % des TPE et PME n'avaient rien engagé ou pensaient manquer l'échéance, et plus d'un dirigeant sur deux ne connaissait pas précisément les sanctions ([Dext](https://dext.com/fr/ressources/etude-preparation-pme-facturation-electronique)).
* **Un mois après le lancement**, au comité de suivi du 8 octobre 2026, plus de 20 millions de factures avaient été échangées pour 70 milliards d'euros, mais **un quart** des entreprises n'avait toujours pas désigné de plateforme. Les difficultés remontées portent sur l'adaptation des logiciels et des processus, les besoins des plus petites entreprises et l'interopérabilité. Aucune sanction ne sera prononcée avant la fin de 2026 ([LégiFiscal](https://www.legifiscal.fr/actualites-fiscales/4687-facturation-electronique-mois-lancement-3-entreprises-4-designe-plateforme.html)).

## Le besoin concret

| Qui | Difficulté | Ce que fait factur-ia |
|---|---|---|
| **PME et TPE** qui facturent depuis Word, Excel ou un ancien logiciel | Elles doivent émettre du Factur-X d'ici septembre 2027 sans changer tout leur outillage. | Convertit leurs PDF en Factur-X EN 16931 et dit précisément ce qui manque avant l'envoi. |
| **Cabinets d'expertise comptable**, première source d'information pour 61 % des entreprises accompagnées selon l'enquête de l'Ordre | Des centaines de clients, des factures hétérogènes, peu de temps. | Contrôle en masse, tri par décision (prête, à corriger, à relire) et par amende encourue. |
| **Services comptables fournisseurs** | Les flux hors réforme (fournisseurs étrangers, B2C, archives, période de tolérance) arrivent encore en PDF ou en scan. | Extraction structurée par OCR et IA, puis contrôles arithmétiques avant la saisie. |
| **Éditeurs et plateformes agréées** | Les rejets coûtent du support. Il faut un contrôle préalable explicable. | API de validation qui relie chaque anomalie à sa règle officielle (BT, BR-FR). |

## Pourquoi de l'IA, et pourquoi pas seulement de l'IA

* **Pourquoi de l'IA** : chaque fournisseur a sa mise en page et une partie des factures sont des scans. Il faut de l'OCR, une reconstruction de la mise en page et, pour les gabarits jamais vus, un LLM capable de lire « Base HT » ou « À l'attention de » sans règle écrite à la main.
* **Pourquoi pas seulement de l'IA** : une facture est un document comptable et fiscal, et un montant inventé par un LLM est inacceptable. factur-ia applique donc des contrôles déterministes (clés de Luhn et mod 97, arithmétique, règles BR-FR officielles), **vérifie que chaque valeur renvoyée par le LLM figure réellement dans le document** et préfère envoyer une facture en revue plutôt que de se tromper en silence.
* **Pourquoi un LLM local** : les factures contiennent des données commerciales sensibles. Le mode par défaut cible un modèle local (Ollama, vLLM), et rien ne sort de l'infrastructure de l'entreprise.

## Ce que factur-ia ne fait pas

* Ce n'est **pas une plateforme agréée**. Il ne transmet rien à l'administration et ne gère pas l'e-reporting. Il se place **avant** la plateforme.
* Il produit le profil Factur-X **EN 16931**. La conformité PDF/A-3 stricte dépend du PDF source.
* Les mesures publiées portent sur des factures **synthétiques** (voir [evaluation.md](evaluation.md)). Un jeu réel annoté est indispensable avant toute mise en production.
