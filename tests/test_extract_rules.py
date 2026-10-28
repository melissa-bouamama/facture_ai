import random
from decimal import Decimal

import pytest

from facturia.evaluate import field_match
from facturia.extract import TRACKED_FIELDS
from facturia.extract.rules import RulesExtractor
from facturia.pipeline import Decision, process
from facturia.reader import read_pdf
from facturia.synth import HELDOUT_TEMPLATES, random_invoice, render_pdf, simulate_scan

from .conftest import HAS_TESSERACT, load_gold


def _get(inv, path):
    for part in path.split("."):
        inv = getattr(inv, part)
    return inv


def test_layout_reconstruction_separates_columns(native_dataset):
    doc = read_pdf(sorted(native_dataset.glob("*.pdf"))[0])
    assert doc.source == "native"
    assert any(len(ln.segments) >= 4 for ln in doc.lines)  # ligne de tableau découpée en cellules


def test_rules_extract_all_fields_on_native_invoices(native_dataset):
    for pdf in sorted(native_dataset.glob("*.pdf")):
        gold, _ = load_gold(pdf)
        ex = RulesExtractor().extract(read_pdf(pdf))
        wrong = [
            f for f in TRACKED_FIELDS if not field_match(f, _get(ex.invoice, f), _get(gold, f))
        ]
        assert wrong == [], f"{pdf.name}: {wrong}"


def test_expected_compliance_issues_are_found(native_dataset):
    for pdf in sorted(native_dataset.glob("*.pdf")):
        _, spec = load_gold(pdf)
        found = {i.code for i in process(pdf).report.issues}
        assert set(spec["expected_issues"]) <= found, pdf.name


def test_unknown_layout_is_routed_to_review_not_silently_wrong():
    rng = random.Random(5)
    for _ in range(3):
        inv, spec = random_invoice(rng, HELDOUT_TEMPLATES)
        report = process(render_pdf(inv, spec, rng)).report
        assert report.decision == Decision.HUMAN_REVIEW


@pytest.mark.slow
@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract absent")
def test_scanned_invoice_goes_through_ocr():
    rng = random.Random(3)
    inv, spec = random_invoice(rng, ["classique"])
    pdf = simulate_scan(render_pdf(inv, spec, rng), rng)
    doc = read_pdf(pdf)
    assert doc.source == "ocr"
    ex = RulesExtractor().extract(doc)
    assert ex.invoice.total_with_vat == inv.total_with_vat
    assert ex.invoice.seller.siren == inv.seller.siren
    assert (
        ex.invoice.lines and sum(ln.net_amount for ln in ex.invoice.lines) == inv.total_without_vat
    )
    assert isinstance(ex.invoice.total_vat, Decimal)
