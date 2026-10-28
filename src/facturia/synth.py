"""Générateur de factures françaises synthétiques, avec vérité terrain.

Pourquoi un générateur ? Les factures réelles contiennent des données personnelles et
commerciales : il n'existe pas de jeu public annoté de factures françaises 2026. Le
générateur produit des PDF réalistes et variés (4 gabarits, libellés synonymes, formats
de dates et de montants différents, mentions obligatoires volontairement omises) ainsi
que le JSON attendu, ce qui permet de mesurer l'extraction et la détection d'anomalies.

Toutes les entreprises sont fictives. Les identifiants (SIREN, SIRET, TVA, IBAN) sont
générés avec des clés de contrôle valides mais ne correspondent à aucune entité réelle
connue.
"""

from __future__ import annotations

import io
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .identifiers import fr_vat_from_siren, iban_check_digits, luhn_complete
from .models import Address, Invoice, InvoiceLine, OperationCategory, Party, VatBreakdown
from .normalize import fmt_amount, money

PREFIXES = ["Nexa", "Vel", "Ori", "Kal", "Sora", "Tali", "Bren", "Lumi", "Arva", "Céli", "Dora",
            "Fenn", "Gali", "Hova", "Iro", "Juno", "Mira", "Nova", "Opa", "Quila", "Rhéa", "Sylv"]  # fmt: skip
SUFFIXES = ["lis", "tek", "nova", "ria", "son", "via", "dor", "mex", "line", "gram", "pharm", "bat"]
ACTIVITIES = ["Conseil", "Solutions", "Industrie", "Services", "Bâtiment", "Distribution",
              "Informatique", "Ingénierie", "Logistique", "Atelier", "Studio", "Analytics"]  # fmt: skip
FORMS = ["SAS", "SARL", "SA", "SASU", "EURL"]
STREET_TYPES = ["rue", "avenue", "boulevard", "allée", "impasse", "place", "quai"]
STREET_NAMES = ["des Lilas", "Victor Hugo", "de la République", "Jean Jaurès", "du Moulin",
                "Pasteur", "des Tanneurs", "Gambetta", "de la Gare", "Saint-Michel",
                "des Acacias", "du Général Leclerc", "Émile Zola", "de Verdun"]  # fmt: skip
CITIES = [("75011", "Paris"), ("69003", "Lyon"), ("13006", "Marseille"), ("31000", "Toulouse"),
          ("44000", "Nantes"), ("59000", "Lille"), ("33000", "Bordeaux"), ("35000", "Rennes"),
          ("67000", "Strasbourg"), ("34000", "Montpellier"), ("38000", "Grenoble"),
          ("21000", "Dijon"), ("92100", "Boulogne-Billancourt"), ("94200", "Ivry-sur-Seine")]  # fmt: skip

GOODS = [("Écran 27 pouces QHD", 289, 20), ("Clavier mécanique sans fil", 89, 20),
         ("Câble HDMI 2 m", 12.5, 20), ("Rame papier A4 80 g (carton de 5)", 24.9, 20),
         ("Cartouche toner noir", 64, 20), ("Chaise de bureau ergonomique", 349, 20),
         ("Livre technique - Apprentissage automatique", 45, 5.5),
         ("Café en grains 1 kg", 18.4, 5.5), ("Lot de 10 cahiers", 15, 20),
         ("Disque SSD 1 To", 79.9, 20), ("Station d'accueil USB-C", 129, 20),
         ("Plateaux repas (lot de 12)", 96, 10)]  # fmt: skip
SERVICES = [("Prestation de conseil - jour", 750, 20), ("Développement logiciel (jour/homme)", 620, 20),
            ("Maintenance annuelle serveur", 1200, 20), ("Formation Python - 2 jours", 1400, 20),
            ("Audit de sécurité", 2500, 20), ("Abonnement hébergement mensuel", 49, 20),
            ("Heure de support technique", 85, 20), ("Rédaction de documentation", 450, 20),
            ("Travaux de rénovation - main d'œuvre", 380, 10), ("Licence logicielle annuelle", 299, 20)]  # fmt: skip

LABELS = {
    "invoice": ["Facture N°", "Facture n°", "N° de facture", "Numéro de facture", "Facture no"],
    "date": ["Date :", "Date de facture :", "Date d'émission :", "Émise le", "Date facture :"],
    "due": ["Échéance :", "Date d'échéance :", "À régler avant le", "Date limite de paiement :"],
    "buyer": ["Facturé à", "Client", "Destinataire", "Adresse de facturation"],
    "delivery": ["Adresse de livraison", "Livré à", "Lieu de livraison"],
    "ht": ["Total HT", "Montant HT", "Total hors taxes", "Sous-total HT"],
    "tva": ["TVA", "T.V.A.", "Montant TVA"],
    "ttc": ["Total TTC", "Montant TTC", "Total toutes taxes comprises"],
    "due_amount": ["Net à payer", "Reste à payer", "Montant à régler"],
}

PENALTY_NOTE = "En cas de retard de paiement, des pénalités au taux de 3 fois le taux d'intérêt légal seront appliquées."
RECOVERY_NOTE = "Indemnité forfaitaire pour frais de recouvrement : 40 €."
DISCOUNT_NOTE = "Pas d'escompte pour paiement anticipé."
DEBITS_NOTE = "Option pour le paiement de la TVA d'après les débits."

TEMPLATES = ["classique", "moderne", "compact", "artisan"]
# Gabarit « hors distribution » : vocabulaire et disposition volontairement absents des
# règles (« Réf. », « À l'attention de », « Base HT », « Total à payer »…). Il sert à
# mesurer honnêtement la généralisation, et surtout à vérifier que les échecs sont
# détectés (routage en revue) plutôt que silencieux.
HELDOUT_TEMPLATES = ["hors-gabarit"]


@dataclass
class SynthSpec:
    """Ce qui a été volontairement inclus ou omis sur la facture générée."""

    template: str
    show_buyer_siren: bool
    show_category: bool
    show_penalties: bool
    show_recovery_fee: bool
    show_discount: bool
    show_delivery: bool
    number_has_space: bool
    expected_issues: list[str] = field(default_factory=list)


def _company(rng: random.Random) -> Party:
    name = (
        f"{rng.choice(PREFIXES)}{rng.choice(SUFFIXES)} {rng.choice(ACTIVITIES)} {rng.choice(FORMS)}"
    )
    siren = luhn_complete("".join(str(rng.randint(0, 9)) for _ in range(8)).replace("0", "1", 1))
    siret = luhn_complete(siren + f"{rng.randint(1, 999):04d}")
    return Party(
        name=name,
        siren=siren,
        siret=siret,
        vat_id=fr_vat_from_siren(siren),
        address=_address(rng),
    )


def _address(rng: random.Random) -> Address:
    postcode, city = rng.choice(CITIES)
    return Address(
        line1=f"{rng.randint(1, 180)} {rng.choice(STREET_TYPES)} {rng.choice(STREET_NAMES)}",
        postcode=postcode,
        city=city,
    )


def _iban(rng: random.Random) -> str:
    bank, branch = f"{rng.randint(10000, 30999)}", f"{rng.randint(10, 99999):05d}"
    account = "".join(str(rng.randint(0, 9)) for _ in range(11))
    rib_key = 97 - ((89 * int(bank) + 15 * int(branch) + 3 * int(account)) % 97)
    bban = f"{bank}{branch}{account}{rib_key:02d}"
    return f"FR{iban_check_digits('FR', bban)}{bban}"


def random_invoice(
    rng: random.Random, templates: list[str] | None = None
) -> tuple[Invoice, SynthSpec]:
    seller, buyer = _company(rng), _company(rng)
    kind = rng.choices(["goods", "services", "mixed"], weights=[3, 4, 2])[0]
    pool = {"goods": GOODS, "services": SERVICES, "mixed": GOODS + SERVICES}[kind]
    n_lines = rng.randint(1, 6)
    items = rng.sample(pool, k=min(n_lines, len(pool)))
    if kind == "mixed" and not ({i[0] for i in items} & {s[0] for s in SERVICES}):
        items[-1] = rng.choice(SERVICES)
    if kind == "mixed" and not ({i[0] for i in items} & {g[0] for g in GOODS}):
        items[0] = rng.choice(GOODS)
    has_goods = any(i in GOODS for i in items)
    has_services = any(i in SERVICES for i in items)
    category = (
        OperationCategory.MIXED
        if has_goods and has_services
        else OperationCategory.GOODS
        if has_goods
        else OperationCategory.SERVICES
    )

    lines = []
    for desc, price, rate in items:
        qty = (
            Decimal(rng.choice([1, 1, 2, 3, 5, 10, 12]))
            if price < 500
            else Decimal(rng.choice([1, 1, 2, 3, 5]))
        )
        unit = money(price)
        lines.append(
            InvoiceLine(
                description=desc,
                quantity=qty,
                unit_price=unit,
                net_amount=money(qty * unit),
                vat_rate=Decimal(str(rate)),
            )
        )
    by_rate: dict[Decimal, Decimal] = {}
    for ln in lines:
        by_rate[ln.vat_rate] = by_rate.get(ln.vat_rate, Decimal(0)) + ln.net_amount
    breakdown = [
        VatBreakdown(rate=r, taxable_amount=money(b), tax_amount=money(b * r / 100))
        for r, b in sorted(by_rate.items(), reverse=True)
    ]
    total_ht = money(sum(ln.net_amount for ln in lines))
    total_tva = money(sum(b.tax_amount for b in breakdown))

    issue = date(2026, 9, 1) + timedelta(days=rng.randint(0, 58))
    number_style = rng.choice(
        ["FA-{y}-{n:04d}", "F{y}/{n:04d}", "INV-{n:05d}", "{y}-{m:02d}-{n:03d}"]
    )
    number = number_style.format(y=issue.year, m=issue.month, n=rng.randint(1, 9999))
    number_has_space = rng.random() < 0.08
    if number_has_space:
        number = number.replace("-", " ", 1).replace("/", " ", 1)

    spec = SynthSpec(
        template=rng.choice(templates or TEMPLATES),
        show_buyer_siren=rng.random() < 0.75,
        show_category=rng.random() < 0.7,
        show_penalties=rng.random() < 0.85,
        show_recovery_fee=rng.random() < 0.85,
        show_discount=rng.random() < 0.7,
        show_delivery=has_goods and rng.random() < 0.45,
        number_has_space=number_has_space,
    )
    vat_on_debits = category == OperationCategory.SERVICES and rng.random() < 0.3

    inv = Invoice(
        number=number,
        issue_date=issue,
        due_date=issue + timedelta(days=rng.choice([15, 30, 45])),
        seller=seller,
        buyer=(
            buyer.model_copy(update={"vat_id": buyer.vat_id if rng.random() < 0.7 else None})
            if spec.show_buyer_siren
            else buyer.model_copy(update={"siren": None, "siret": None, "vat_id": None})
        ),
        delivery_address=_address(rng) if spec.show_delivery else None,
        operation_category=category if spec.show_category else None,
        vat_on_debits=vat_on_debits,
        lines=lines,
        vat_breakdown=breakdown,
        total_without_vat=total_ht,
        total_vat=total_tva,
        total_with_vat=total_ht + total_tva,
        amount_due=total_ht + total_tva,
        iban=_iban(rng),
        bic=rng.choice(["BNPAFRPPXXX", "AGRIFRPP882", "CEPAFRPP751", "SOGEFRPPXXX"]),
        payment_terms=rng.choice(
            ["Paiement à 30 jours", "Virement bancaire", "Paiement par virement à réception"]
        ),
        late_penalty_note=PENALTY_NOTE if spec.show_penalties else None,
        recovery_fee_note=RECOVERY_NOTE if spec.show_recovery_fee else None,
        discount_note=DISCOUNT_NOTE if spec.show_discount else None,
    )
    if not spec.show_buyer_siren:
        spec.expected_issues.append("FR-BUYER-SIREN-MISSING")
    if not spec.show_category:
        spec.expected_issues.append("FR-OPERATION-CATEGORY-MISSING")
    if not spec.show_penalties:
        spec.expected_issues.append("FR-NOTE-PENALTIES-MISSING")
    if not spec.show_recovery_fee:
        spec.expected_issues.append("FR-NOTE-RECOVERY-FEE-MISSING")
    if not spec.show_discount:
        spec.expected_issues.append("FR-NOTE-DISCOUNT-MISSING")
    if number_has_space:
        spec.expected_issues.append("FR-INVOICE-NUMBER-FORMAT")
    return inv, spec


# --------------------------------------------------------------------------- rendu PDF


def _fmt_date(d: date, rng: random.Random) -> str:
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
              "septembre", "octobre", "novembre", "décembre"]  # fmt: skip
    return rng.choice(
        [
            d.strftime("%d/%m/%Y"),
            f"{d.day} {months[d.month - 1]} {d.year}",
            d.isoformat(),
            d.strftime("%d.%m.%Y"),
        ]
    )


def _fmt_money(v: Decimal, style: str) -> str:
    s = fmt_amount(v)
    return {"eur_sign": f"{s} €", "plain": s, "eur_code": f"{s} EUR"}[style]


def _fmt_rate(r: Decimal) -> str:
    return f"{r.normalize():f}".replace(".", ",") + " %"


def render_pdf(inv: Invoice, spec: SynthSpec, rng: random.Random) -> bytes:
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    accent = HexColor(rng.choice(["#1f4e79", "#7a1f3d", "#245c3a", "#4b3f72", "#333333"]))
    money_style = rng.choice(["eur_sign", "plain", "eur_code"])
    lab = {k: rng.choice(v) for k, v in LABELS.items()}
    t = spec.template
    s, b = inv.seller, inv.buyer

    def text(x, y, value, size=9, bold=False, color=black, right=False):
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (c.drawRightString if right else c.drawString)(x, y, value)
        c.setFillColor(black)

    def party_block(x, y, title, p: Party, ids: bool):
        if title:
            text(x, y, title, 9, bold=True, color=accent)
            y -= 13
        text(x, y, p.name or "", 10, bold=True)
        y -= 12
        for line in [p.address.line1, f"{p.address.postcode} {p.address.city}"]:
            text(x, y, line or "")
            y -= 11
        if ids and p.siren:
            text(
                x,
                y,
                rng.choice([f"SIREN : {p.siren}", f"SIREN {p.siren}", f"N° SIREN : {p.siren}"]),
            )
            y -= 11
            if p.vat_id:
                text(x, y, f"TVA intracom. : {p.vat_id}")
                y -= 11
        return y

    # ---- en-tête
    meta = [
        (lab["invoice"], inv.number),
        (lab["date"].rstrip(" :"), _fmt_date(inv.issue_date, rng)),
        (lab["due"].rstrip(" :"), _fmt_date(inv.due_date, rng)),
    ]
    if t == "hors-gabarit":
        text(40, H - 50, "À l'attention de :", 9, color=accent)
        text(40, H - 63, b.name, 10, bold=True)
        text(40, H - 75, b.address.line1)
        text(40, H - 86, f"{b.address.postcode} {b.address.city}")
        if b.siren:
            text(40, H - 97, f"Identifiant client (SIREN) : {b.siren}")
        text(330, H - 50, s.name, 11, bold=True)
        text(330, H - 63, f"{s.address.line1} - {s.address.postcode} {s.address.city}", 8)
        text(330, H - 74, f"SIRET : {s.siret}", 8)
        text(330, H - 85, f"N° TVA : {s.vat_id}", 8)
        text(W / 2 - 30, H - 135, "Facture", 16, bold=True, color=accent)
        text(40, H - 160, f"Réf. : {inv.number}")
        text(40, H - 172, f"{s.address.city}, le {_fmt_date(inv.issue_date, rng)}")
        text(40, H - 184, f"Paiement au plus tard le {_fmt_date(inv.due_date, rng)}")
        y = H - 205
        if inv.delivery_address:
            text(40, y, f"Expédition : {inv.delivery_address.one_line()}")
            y -= 14
        y -= 10
    elif t == "moderne":
        c.setFillColor(accent)
        c.rect(0, H - 90, W, 90, fill=1, stroke=0)
        text(40, H - 45, s.name, 16, bold=True, color=white)
        text(
            40, H - 62, f"{s.address.line1}, {s.address.postcode} {s.address.city}", 9, color=white
        )
        text(W - 40, H - 45, "FACTURE", 20, bold=True, color=white, right=True)
        y = H - 120
        for k, v in meta:
            text(40, y, k, 9, bold=True)
            text(170, y, v)
            y -= 13
        y_parties = y - 15
        y_left = party_block(40, y_parties, lab["buyer"], b, ids=True)
        y_right = y_parties
        if inv.delivery_address:
            y_right = party_block(
                320,
                y_parties,
                lab["delivery"],
                Party(name=b.name, address=inv.delivery_address),
                ids=False,
            )
        y = min(y_left, y_right) - 20
    elif t == "compact":
        text(40, H - 50, s.name, 13, bold=True)
        text(40, H - 64, f"{s.address.line1} - {s.address.postcode} {s.address.city}", 9)
        text(40, H - 76, f"SIRET {s.siret} - TVA {s.vat_id}", 8)
        y = H - 110
        text(40, y, f"{lab['invoice']} {inv.number}", 14, bold=True)
        y -= 18
        text(40, y, f"{meta[1][0]} : {meta[1][1]}    {meta[2][0]} : {meta[2][1]}")
        y -= 28
        y = party_block(40, y, lab["buyer"] + " :", b, ids=True)
        if inv.delivery_address:
            y -= 6
            y = party_block(
                40,
                y,
                lab["delivery"] + " :",
                Party(name=b.name, address=inv.delivery_address),
                ids=False,
            )
        y -= 18
    else:  # classique / artisan
        y = party_block(40, H - 50, None, s, ids=False)
        text(
            40,
            y,
            f"Tél. 0{rng.randint(1, 5)} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
        )
        text(W - 40, H - 50, "FACTURE", 18, bold=True, color=accent, right=True)
        ym = H - 72
        for k, v in meta:
            text(
                W - 40,
                ym,
                f"{k} {v}" if k.endswith("°") or k.endswith("no") else f"{k} : {v}",
                9,
                right=True,
            )
            ym -= 12
        y_b = party_block(320, H - 140, lab["buyer"], b, ids=True)
        y_d = y_b
        if inv.delivery_address:
            y_d = party_block(
                40,
                H - 140,
                lab["delivery"],
                Party(name=b.name, address=inv.delivery_address),
                ids=False,
            )
        y = min(y_b, y_d, y - 20) - 20

    if spec.show_category and inv.operation_category:
        label = "Nature de l'opération" if t == "hors-gabarit" else "Catégorie d'opération"
        text(40, y, f"{label} : {inv.operation_category.label}", 9, bold=True)
        y -= 18

    # ---- tableau des lignes
    with_vat_col = t in ("moderne", "artisan") or len(inv.vat_breakdown) > 1
    cols = [("Désignation", 40), ("Qté", 330), ("PU HT", 400)]
    if t == "artisan":
        cols = [("Réf.", 40), ("Désignation", 80), ("Qté", 330), ("PU HT", 400)]
    if t == "hors-gabarit":
        cols = [("Libellé", 40), ("Quantité", 330), ("Prix unitaire", 390)]
    if with_vat_col:
        cols.append(("Taux TVA" if t == "hors-gabarit" else "TVA", 455))
    total_header = "Montant" if t == "hors-gabarit" else "Total HT"
    cols.append((total_header, W - 40))
    c.setFillColor(HexColor("#e9edf2") if t != "compact" else white)
    c.rect(36, y - 4, W - 72, 16, fill=1, stroke=0)
    for name, x in cols:
        text(x, y, name, 9, bold=True, right=(name == total_header))
    y -= 18
    for i, ln in enumerate(inv.lines, start=1):
        x_desc = 80 if t == "artisan" else 40
        if t == "artisan":
            text(40, y, f"R{100 + i}")
        desc = ln.description
        if len(desc) > 42 and rng.random() < 0.6:  # description sur deux lignes
            cut = desc.rfind(" ", 0, 42)
            text(x_desc, y, desc[:cut])
            text(x_desc, y - 11, desc[cut + 1 :])
        else:
            text(x_desc, y, desc)
        text(330, y, f"{ln.quantity}")
        text(400, y, fmt_amount(ln.unit_price))
        if with_vat_col:
            text(455, y, _fmt_rate(ln.vat_rate))
        text(W - 40, y, fmt_amount(ln.net_amount), right=True)
        y -= 26 if len(desc) > 42 else 15
        if t == "artisan":
            c.setStrokeColor(HexColor("#cccccc"))
            c.line(36, y + 9, W - 36, y + 9)
    y -= 10

    # ---- totaux
    xl, xr = 340, W - 40
    if t == "hors-gabarit":
        lab.update(
            {"ht": "Base HT", "tva": "TVA à", "ttc": "Total à payer", "due_amount": "Total à payer"}
        )
    rows = [(lab["ht"], inv.total_without_vat)]
    for vb in inv.vat_breakdown:
        rows.append((f"{lab['tva']} {_fmt_rate(vb.rate)}", vb.tax_amount))
    rows.append((lab["ttc"], inv.total_with_vat))
    if rng.random() < 0.6 and t != "hors-gabarit":
        rows.append((lab["due_amount"], inv.amount_due))
    for k, v in rows:
        bold = k in (lab["ttc"], lab["due_amount"])
        text(xl, y, k, 10 if bold else 9, bold=bold)
        text(xr, y, _fmt_money(v, money_style), 10 if bold else 9, bold=bold, right=True)
        y -= 14

    # ---- paiement et mentions
    y -= 14
    text(40, y, "Conditions de paiement", 9, bold=True, color=accent)
    y -= 12
    text(40, y, f"{inv.payment_terms}. IBAN : {_spaced_iban(inv.iban)} - BIC : {inv.bic}", 8)
    y -= 11
    notes = [n for n in [inv.late_penalty_note, inv.recovery_fee_note, inv.discount_note] if n]
    if inv.vat_on_debits:
        notes.append(DEBITS_NOTE)
    for n in notes:
        text(40, y, n, 7.5)
        y -= 10

    # ---- pied de page légal
    footer = (
        f"{s.name} - capital de {rng.choice([1000, 5000, 10000, 50000])} € - RCS {s.address.city} "
        f"{s.siren} - SIRET {s.siret} - N° TVA {s.vat_id}"
    )
    if t == "compact":
        footer = f"{s.name} - RCS {s.address.city} {s.siren}"
    if t == "hors-gabarit":
        footer = f"Merci de rappeler la référence {inv.number} lors de votre règlement."
    text(W / 2 - c.stringWidth(footer, "Helvetica", 7) / 2, 30, footer, 7)
    c.showPage()
    c.save()
    return buf.getvalue()


def _spaced_iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def simulate_scan(pdf_bytes: bytes, rng: random.Random, dpi: int = 200) -> bytes:
    """Dégrade un PDF natif en PDF image (rotation, bruit, flou, JPEG) pour tester l'OCR."""
    import numpy as np
    import pdfplumber
    from PIL import Image, ImageFilter

    images = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            img = p.to_image(resolution=dpi).original.convert("L")
            img = img.rotate(
                rng.uniform(-1.2, 1.2), expand=False, fillcolor=255, resample=Image.BICUBIC
            )
            arr = np.asarray(img).astype(np.float32)
            arr += np.random.default_rng(rng.randint(0, 10**6)).normal(
                0, rng.uniform(4, 12), arr.shape
            )
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
            jpeg = io.BytesIO()
            img.save(jpeg, "JPEG", quality=rng.randint(45, 75))
            images.append(Image.open(io.BytesIO(jpeg.getvalue())).convert("RGB"))
    out = io.BytesIO()
    images[0].save(out, "PDF", resolution=dpi, save_all=True, append_images=images[1:])
    return out.getvalue()


def ground_truth(inv: Invoice, spec: SynthSpec) -> dict:
    data = json.loads(inv.model_dump_json())
    data["_spec"] = {
        "template": spec.template,
        "expected_issues": spec.expected_issues,
        "show_buyer_siren": spec.show_buyer_siren,
    }
    return data


def generate_dataset(
    out_dir: str | Path,
    n: int = 50,
    seed: int = 42,
    scanned_ratio: float = 0.3,
    templates: list[str] | None = None,
) -> list[Path]:
    """Écrit `n` factures (PDF + JSON) dans `out_dir`, dont une partie dégradée en scan."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    paths = []
    for i in range(n):
        inv, spec = random_invoice(rng, templates)
        pdf = render_pdf(inv, spec, rng)
        scanned = rng.random() < scanned_ratio
        if scanned:
            pdf = simulate_scan(pdf, rng)
        stem = f"facture_{i:03d}{'_scan' if scanned else ''}"
        (out / f"{stem}.pdf").write_bytes(pdf)
        gt = ground_truth(inv, spec)
        gt["_spec"]["scanned"] = scanned
        (out / f"{stem}.json").write_text(
            json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        paths.append(out / f"{stem}.pdf")
    return paths


# --------------------------------------------------------------------------- démo

DEMO_SAMPLES = {
    "corriger": "Facture à corriger",
    "conforme": "Facture conforme",
    "scan": "Facture scannée",
    "inconnue": "Mise en page inconnue",
}
_NEW_MENTIONS = {"FR-BUYER-SIREN-MISSING", "FR-OPERATION-CATEGORY-MISSING"}


def sample_pdf(kind: str, seed: int = 0) -> bytes:
    """Facture d'exemple pour la démo.

    `corriger` : les nouvelles mentions 2026 manquent. `conforme` : aucune anomalie.
    `scan` : facture conforme dégradée en scan. `inconnue` : gabarit hors distribution.
    `hasard` : tirage libre (30 % de scans).
    """
    if kind not in {*DEMO_SAMPLES, "hasard"}:
        raise ValueError(f"exemple inconnu : {kind}")
    templates = HELDOUT_TEMPLATES if kind == "inconnue" else TEMPLATES
    while True:
        rng = random.Random(seed)
        inv, spec = random_invoice(rng, templates)
        issues = set(spec.expected_issues)
        wanted = {
            "corriger": issues >= _NEW_MENTIONS,
            "conforme": not issues,
            "scan": not issues,
            "inconnue": True,
            "hasard": True,
        }[kind]
        if wanted and len(inv.lines) >= 2:
            break
        seed += 1
    pdf = render_pdf(inv, spec, rng)
    if kind == "scan" or (kind == "hasard" and rng.random() < 0.3):
        pdf = simulate_scan(pdf, rng)
    return pdf
