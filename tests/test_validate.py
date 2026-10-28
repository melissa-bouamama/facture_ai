from datetime import date
from decimal import Decimal

from facturia.models import OperationCategory
from facturia.validate import Severity, fine_exposure, guess_category, validate

TODAY = date(2026, 10, 28)


def codes(inv, severity=Severity.ERROR):
    return {i.code for i in validate(inv, today=TODAY) if i.severity == severity}


def test_complete_invoice_has_no_blocking_issue(complete_invoice):
    assert codes(complete_invoice) == set()


def test_new_2026_mentions_are_required(complete_invoice):
    inv = complete_invoice.model_copy(deep=True)
    inv.buyer.siren = None
    inv.operation_category = None
    found = codes(inv)
    assert {"FR-BUYER-SIREN-MISSING", "FR-OPERATION-CATEGORY-MISSING"} <= found
    issue = next(i for i in validate(inv, today=TODAY) if i.code == "FR-OPERATION-CATEGORY-MISSING")
    assert issue.suggestion == "Prestation de services, code PS"  # les lignes sont des prestations
    assert issue.bt == "BT-23" and issue.rule == "BR-FR-08"


def test_invoice_number_with_space_is_rejected(complete_invoice):
    inv = complete_invoice.model_copy(update={"number": "FA 2026 0042"})
    issue = next(i for i in validate(inv, today=TODAY) if i.code == "FR-INVOICE-NUMBER-FORMAT")
    assert issue.suggestion == "FA-2026-0042"


def test_arithmetic_rules(complete_invoice):
    inv = complete_invoice.model_copy(update={"total_with_vat": Decimal("4400.00")})
    assert "TOTALS-UNBALANCED" in codes(inv)
    inv = complete_invoice.model_copy(update={"total_without_vat": Decimal("3600.00")})
    assert "LINES-SUM-MISMATCH" in codes(inv)


def test_invalid_identifiers(complete_invoice):
    inv = complete_invoice.model_copy(deep=True)
    inv.seller.siren = "732829321"
    inv.seller.vat_id = "FR45732829320"
    assert {"FR-SELLER-SIREN-INVALID", "SELLER-VAT-INVALID"} <= codes(inv)


def test_french_vat_rates(complete_invoice):
    inv = complete_invoice.model_copy(deep=True)
    inv.lines[0].vat_rate = Decimal("19")
    assert "FR-VAT-RATE-INVALID" in codes(inv)


def test_fine_exposure_is_capped(complete_invoice):
    inv = complete_invoice.model_copy(deep=True)
    inv.buyer.siren = None
    inv.operation_category = None
    issues = validate(inv, today=TODAY)
    assert fine_exposure(issues, inv) == Decimal("30.00")
    small = inv.model_copy(update={"total_with_vat": Decimal("40.00")})
    assert fine_exposure(issues, small) == Decimal("10.00")  # 25 % de 40 €


def test_guess_category(complete_invoice):
    assert guess_category(complete_invoice) == OperationCategory.SERVICES
