"""Mises en page observées sur de vraies factures, reproduites avec des données fictives.

Facture d'hébergement produite par un logiciel de gestion hôtelière, adressée à un
particulier : numéro dans le titre, raison sociale annoncée par « Nom de la société »,
tableau sans colonne de désignation dont le total est TTC, totaux dans un récapitulatif
de TVA, solde nul (facture réglée) et SIRET imprimé avec 13 chiffres.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest

from facturia.export.schematron import saxon_available
from facturia.models import Party
from facturia.normalize import parse_rate
from facturia.pipeline import Decision, process
from facturia.validate import buyer_is_individual

W, H = 595, 842


def _hotel_invoice() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))

    def text(x, y, s, size=9, bold=False, right=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (c.drawRightString if right else c.drawString)(x, y, s)

    text(W - 40, H - 45, "FACTURE 2025117", 16, bold=True, right=True)
    text(45, H - 95, "LES TILLEULS", 11)
    rows = [
        ("Nom de la société.", "Tilleuls Hôtellerie"),
        ("Adresse", "4 rue des Tilleuls,"),
        ("", "Lyon, 69002, France"),
        ("Numéro de TVA", "FR44732829320"),
        ("SIRET", "7328293200007"),
        ("NAF", "5520Z"),
    ]
    for k, (label, value) in enumerate(rows):
        y = H - 140 - 12 * k
        if label:
            text(20, y, label, bold=True)
        text(230, y, value, right=False)
    for k, (label, value) in enumerate(
        [("RCS", "Lyon B 732 829 320"), ("Statut légal", "SAS"), ("Ville", "Lyon")]
    ):
        text(340, H - 140 - 12 * k, label, bold=True)
        text(W - 40, H - 140 - 12 * k, value, right=True)

    # libellé en gras, valeur légèrement plus basse : deux lignes après reconstruction
    text(20, H - 222, "Date d'émission", 11, bold=True)
    text(190, H - 228, "15/09/2026   10:12:05", 10)
    text(330, H - 222, "Client", 12, bold=True)
    text(332, H - 240, "MARTIN Claire", 10)

    text(25, H - 270, "HÉBERGEMENT", 16, bold=True)
    text(24, H - 290, "ÉLÉMENTS DE FACTURE", 10, bold=True)
    text(23, H - 304, "Hébergement 112 (01/09/2026 - 14/09/2026, CHAMBRE 3)", 8)

    # « PRIX TTC » et « QUANTITÉ » assez proches pour former une seule cellule, comme à l'OCR
    header = [("CONSOMMÉ", 250), ("PRIX HT", 318), ("TVA", 385), ("PRIX TTC", 425)]
    for name, x in header:
        text(x, H - 340, name, bold=True)
    text(470, H - 340, "QUANTITÉ", bold=True)
    text(W - 35, H - 340, "TOTAL", bold=True, right=True)
    for value, x in [("14/09/2026", 255), ("80 €", 330), ("8,00 € (10%)", 362), ("88,00 €", 430)]:
        text(x, H - 355, value)
    text(488, H - 355, "14")
    text(W - 35, H - 355, "1232 €", right=True)

    text(40, H - 385, "TOTAL", 10, bold=True)
    text(W - 40, H - 385, "1232,00 €", 10, bold=True, right=True)
    for name, x in [("TAUX TVA", 300), ("PRIX HT", 380), ("TVA", 460)]:
        text(x, H - 410, name, bold=True)
    text(W - 40, H - 410, "MONTANT", bold=True, right=True)
    for value, x in [("10 %", 310), ("80,00 €", 380), ("8,00 €", 460)]:
        text(x, H - 425, value)
    text(W - 40, H - 425, "88,00 €", right=True)
    for value, x in [("Total", 300), ("1120,00 €", 380), ("112,00 €", 460)]:
        text(x, H - 437, value, bold=True)
    text(W - 40, H - 437, "1232,00 €", bold=True, right=True)

    text(40, H - 470, "SOLDE", 10, bold=True)
    text(W - 40, H - 470, "0,00 €", 10, bold=True, right=True)
    text(
        44,
        H - 540,
        "Pour tout professionnel, toute somme non payée à sa date d'exigibilité produira le "
        "paiement d'une indemnité forfaitaire de 40 euros due au titre des frais de recouvrement.",
        7,
    )
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="module")
def hotel_result():
    return process(_hotel_invoice(), schematron=True, build_xml=True)


def test_hotel_invoice_fields(hotel_result):
    inv = hotel_result.report.invoice
    assert inv.number == "2025117"  # porté par le titre
    assert inv.seller.name == "Tilleuls Hôtellerie"  # libellé « Nom de la société », pas le titre
    assert inv.seller.siren == "732829320"
    assert inv.buyer.name == "MARTIN Claire"  # bloc « Client » malgré la date intercalée
    assert str(inv.issue_date) == "2026-09-15"
    (line,) = inv.lines
    assert line.description.startswith("Hébergement 112")  # désignation au-dessus du tableau
    # colonne TOTAL en TTC : 14 × 88 = 1232, le montant HT est 14 × 80
    assert (line.quantity, line.unit_price, line.net_amount) == (14, 80, Decimal("1120.00"))
    assert line.vat_rate == 10
    assert (inv.total_without_vat, inv.total_vat, inv.total_with_vat) == (1120, 112, 1232)
    assert inv.amount_due == 0  # « SOLDE 0,00 € » : facture réglée


def test_hotel_invoice_is_b2c_and_ready(hotel_result):
    report = hotel_result.report
    codes = {i.code for i in report.issues}
    assert "B2C-BUYER-INDIVIDUAL" in codes
    assert "FR-SELLER-SIRET-INVALID" in codes  # 13 chiffres
    # obligations réservées aux échanges entre entreprises : non exigées ici
    assert not codes & {
        "FR-BUYER-SIREN-MISSING",
        "FR-OPERATION-CATEGORY-MISSING",
        "FR-NOTE-PENALTIES-MISSING",
        "FR-NOTE-DISCOUNT-MISSING",
    }
    assert report.fine_exposure_eur == 0
    assert report.decision == Decision.READY


@pytest.mark.skipif(not saxon_available(), reason="saxonche non installé")
def test_hotel_invoice_xml_is_valid_en16931(hotel_result):
    report = hotel_result.report
    assert report.schematrons_run == ["en16931"]  # BR-FR ne vise que le B2B
    assert report.xml_valid
    xml = hotel_result.xml.decode()
    assert "<ram:TotalPrepaidAmount>1232.00</ram:TotalPrepaidAmount>" in xml
    assert "7328293200007" not in xml  # SIRET invalide signalé, jamais exporté


@pytest.mark.parametrize(
    "name,individual",
    [
        ("MARTIN Claire", True),
        ("Mme Claire Martin", True),
        ("Claire Martin", False),  # sans nom en capitales, on reste prudent : règles B2B
        ("Sorabat Industrie SARL", False),
        ("ACME CONSEIL", False),
    ],
)
def test_buyer_is_individual(name, individual):
    assert buyer_is_individual(Party(name=name)) is individual
    assert buyer_is_individual(Party(name=name, siren="418273645")) is False


def test_rate_is_serialized_without_exponent():
    assert str(parse_rate("10 %")) == "10" and str(parse_rate("5,5 %")) == "5.5"
