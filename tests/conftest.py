from __future__ import annotations

import importlib.util
import json
import random
from datetime import date
from decimal import Decimal

import pytest

from facturia.models import Address, Invoice, InvoiceLine, OperationCategory, Party, VatBreakdown
from facturia.synth import generate_dataset, random_invoice, render_pdf

HAS_OCR = importlib.util.find_spec("doctr") is not None


@pytest.fixture
def complete_invoice() -> Invoice:
    """Facture française conforme : toutes les mentions, montants justes."""
    return Invoice(
        number="FA-2026-0042",
        issue_date=date(2026, 9, 15),
        due_date=date(2026, 10, 15),
        seller=Party(
            name="Nexalis Conseil SAS",
            siren="732829320",
            siret="73282932000074",
            vat_id="FR44732829320",
            address=Address(line1="12 rue des Lilas", postcode="75011", city="Paris"),
        ),
        buyer=Party(
            name="Sorabat Industrie SARL",
            siren="418273645",
            vat_id="FR41418273645",
            address=Address(line1="3 quai de la Gare", postcode="69003", city="Lyon"),
        ),
        operation_category=OperationCategory.SERVICES,
        lines=[
            InvoiceLine(
                description="Prestation de conseil - jour",
                quantity=Decimal(3),
                unit_price=Decimal("750.00"),
                net_amount=Decimal("2250.00"),
                vat_rate=Decimal(20),
            ),
            InvoiceLine(
                description="Formation Python - 2 jours",
                quantity=Decimal(1),
                unit_price=Decimal("1400.00"),
                net_amount=Decimal("1400.00"),
                vat_rate=Decimal(20),
            ),
        ],
        vat_breakdown=[
            VatBreakdown(
                rate=Decimal(20), taxable_amount=Decimal("3650.00"), tax_amount=Decimal("730.00")
            )
        ],
        total_without_vat=Decimal("3650.00"),
        total_vat=Decimal("730.00"),
        total_with_vat=Decimal("4380.00"),
        amount_due=Decimal("4380.00"),
        iban="FR7630006000011234567890189",
        bic="AGRIFRPP882",
        payment_terms="Paiement à 30 jours",
        late_penalty_note="Pénalités de retard : 3 fois le taux d'intérêt légal.",
        recovery_fee_note="Indemnité forfaitaire pour frais de recouvrement : 40 €.",
        discount_note="Pas d'escompte pour paiement anticipé.",
    )


@pytest.fixture(scope="session")
def native_dataset(tmp_path_factory):
    """12 factures natives (sans scan) couvrant les 4 gabarits."""
    folder = tmp_path_factory.mktemp("native")
    generate_dataset(folder, n=12, seed=2026, scanned_ratio=0.0)
    return folder


@pytest.fixture(scope="session")
def sample_pdf():
    rng = random.Random(11)
    inv, spec = random_invoice(rng)
    return render_pdf(inv, spec, rng), inv, spec


def load_gold(pdf_path) -> tuple[Invoice, dict]:
    raw = json.loads(pdf_path.with_suffix(".json").read_text(encoding="utf-8"))
    spec = raw.pop("_spec")
    return Invoice.model_validate(raw), spec
