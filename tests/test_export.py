import pytest

from facturia.export.cii import ExportError, build_cii
from facturia.export.pdf import embed_facturx, read_facturx_xml
from facturia.export.schematron import check_xml, check_xsd, saxon_available
from facturia.models import Invoice

needs_saxon = pytest.mark.skipif(not saxon_available(), reason="saxonche non installé")


def test_cii_is_valid_against_official_xsd(complete_invoice):
    ok, err = check_xsd(build_cii(complete_invoice))
    assert ok, err


@needs_saxon
def test_complete_invoice_passes_en16931_and_br_fr_schematrons(complete_invoice):
    report = check_xml(build_cii(complete_invoice))
    blocking = [f for f in report.failures if f["flag"] in ("fatal", "error")]
    assert report.schematron_run == ["en16931", "br-fr"]
    assert blocking == []


@needs_saxon
def test_br_fr_schematron_agrees_with_our_validator(complete_invoice):
    inv = complete_invoice.model_copy(deep=True)
    inv.operation_category = None
    inv.late_penalty_note = None
    ids = {f["id"] for f in check_xml(build_cii(inv)).failures}
    assert "BR-FR-08_BT-23" in ids  # catégorie d'opération / cadre de facturation
    assert "BR-FR-05_BT-22_PMD" in ids  # pénalités de retard


def test_export_refuses_incomplete_invoice():
    with pytest.raises(ExportError):
        build_cii(Invoice(number="X1"))


def test_facturx_round_trip(complete_invoice, sample_pdf):
    pdf, _, _ = sample_pdf
    xml = build_cii(complete_invoice)
    out = embed_facturx(pdf, xml, complete_invoice)
    assert out.startswith(b"%PDF")
    assert read_facturx_xml(out) == xml
