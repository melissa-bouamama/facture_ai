"""Génération du XML Cross Industry Invoice (CII D16B), profil Factur-X EN 16931.

L'ordre des éléments suit strictement le schéma XSD : le XML produit est validé contre
le XSD officiel livré avec la bibliothèque `factur-x`, et peut l'être contre les
schematrons EN 16931 et BR-FR (voir `facturia.export.schematron`).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from lxml import etree

from ..models import Address, Invoice, Party
from ..normalize import money

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}
EN16931_GUIDELINE = "urn:cen.eu:en16931:2017"


class ExportError(ValueError):
    """La facture n'a pas les données minimales pour produire un XML valide."""


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _sub(parent, tag: str, text: str | None = None, **attrs):
    prefix, name = tag.split(":")
    el = etree.SubElement(parent, _q(prefix, name), **attrs)
    if text is not None:
        el.text = str(text)
    return el


def _amount(v: Decimal | None) -> str:
    return f"{money(v or 0):.2f}"


def _rate(v: Decimal) -> str:
    s = f"{Decimal(v).normalize():f}"
    return s


def _date(parent, tag: str, d) -> None:
    holder = _sub(parent, tag)
    _sub(holder, "udt:DateTimeString", d.strftime("%Y%m%d"), format="102")


def _note(parent, content: str, subject: str) -> None:
    note = _sub(parent, "ram:IncludedNote")
    _sub(note, "ram:Content", content)
    _sub(note, "ram:SubjectCode", subject)


def _address(parent, tag: str, addr: Address) -> None:
    a = _sub(parent, tag)
    if addr.postcode:
        _sub(a, "ram:PostcodeCode", addr.postcode)
    if addr.line1:
        _sub(a, "ram:LineOne", addr.line1)
    if addr.line2:
        _sub(a, "ram:LineTwo", addr.line2)
    if addr.city:
        _sub(a, "ram:CityName", addr.city)
    _sub(a, "ram:CountryID", addr.country_code or "FR")


def _party(parent, tag: str, p: Party, with_vat: bool = True) -> None:
    el = _sub(parent, tag)
    if p.siret:
        _sub(el, "ram:GlobalID", p.siret, schemeID="0009")
    _sub(el, "ram:Name", p.name or "")
    if p.siren:
        legal = _sub(el, "ram:SpecifiedLegalOrganization")
        _sub(legal, "ram:ID", p.siren, schemeID="0002")
    _address(el, "ram:PostalTradeAddress", p.address)
    if p.siren:  # adresse électronique de facturation : par défaut le SIREN (annuaire PPF)
        uri = _sub(el, "ram:URIUniversalCommunication")
        _sub(uri, "ram:URIID", p.siren, schemeID="0225")
    if with_vat and p.vat_id:
        reg = _sub(el, "ram:SpecifiedTaxRegistration")
        _sub(reg, "ram:ID", p.vat_id, schemeID="VA")


def _vat_groups(inv: Invoice) -> list[tuple[Decimal, Decimal, Decimal]]:
    """(taux, base, montant) par taux ; recalculés depuis les lignes si besoin."""
    if inv.vat_breakdown:
        return [(vb.rate, vb.taxable_amount, vb.tax_amount) for vb in inv.vat_breakdown]
    bases: dict[Decimal, Decimal] = defaultdict(Decimal)
    for ln in inv.lines:
        bases[ln.vat_rate or Decimal(0)] += ln.net_amount or Decimal(0)
    return [(r, money(b), money(b * r / 100)) for r, b in bases.items()]


def build_cii(inv: Invoice) -> bytes:
    """Construit le XML CII (Factur-X EN 16931) d'une facture."""
    missing = [n for n, v in [("numéro", inv.number), ("date", inv.issue_date),
                               ("vendeur", inv.seller.name), ("acheteur", inv.buyer.name)] if not v]  # fmt: skip
    if missing or not inv.lines:
        raise ExportError(
            f"Données insuffisantes pour l'export : {', '.join(missing or ['lignes'])}"
        )

    root = etree.Element(_q("rsm", "CrossIndustryInvoice"), nsmap=NS)

    ctx = _sub(root, "rsm:ExchangedDocumentContext")
    if inv.operation_category:
        bp = _sub(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter")
        _sub(bp, "ram:ID", inv.operation_category.billing_mode)
    gl = _sub(ctx, "ram:GuidelineSpecifiedDocumentContextParameter")
    _sub(gl, "ram:ID", EN16931_GUIDELINE)

    doc = _sub(root, "rsm:ExchangedDocument")
    _sub(doc, "ram:ID", inv.number)
    _sub(doc, "ram:TypeCode", inv.type_code)
    _date(doc, "ram:IssueDateTime", inv.issue_date)
    if inv.buyer.siren:
        _note(doc, "B2B", "BAR")
    if inv.late_penalty_note:
        _note(doc, inv.late_penalty_note, "PMD")
    if inv.recovery_fee_note:
        _note(doc, inv.recovery_fee_note, "PMT")
    if inv.discount_note:
        _note(doc, inv.discount_note, "AAB")

    tx = _sub(root, "rsm:SupplyChainTradeTransaction")
    for i, ln in enumerate(inv.lines, start=1):
        item = _sub(tx, "ram:IncludedSupplyChainTradeLineItem")
        _sub(_sub(item, "ram:AssociatedDocumentLineDocument"), "ram:LineID", str(i))
        _sub(_sub(item, "ram:SpecifiedTradeProduct"), "ram:Name", ln.description)
        agreement = _sub(item, "ram:SpecifiedLineTradeAgreement")
        unit_price = (
            ln.unit_price
            if ln.unit_price is not None
            else (money((ln.net_amount or 0) / ln.quantity) if ln.quantity else ln.net_amount)
        )
        _sub(
            _sub(agreement, "ram:NetPriceProductTradePrice"),
            "ram:ChargeAmount",
            _amount(unit_price),
        )
        delivery = _sub(item, "ram:SpecifiedLineTradeDelivery")
        _sub(
            delivery,
            "ram:BilledQuantity",
            f"{Decimal(ln.quantity).normalize():f}",
            unitCode=ln.unit_code,
        )
        settle = _sub(item, "ram:SpecifiedLineTradeSettlement")
        tax = _sub(settle, "ram:ApplicableTradeTax")
        _sub(tax, "ram:TypeCode", "VAT")
        rate = ln.vat_rate if ln.vat_rate is not None else Decimal(0)
        _sub(tax, "ram:CategoryCode", "S" if rate > 0 else "Z")
        _sub(tax, "ram:RateApplicablePercent", _rate(rate))
        summ = _sub(settle, "ram:SpecifiedTradeSettlementLineMonetarySummation")
        _sub(summ, "ram:LineTotalAmount", _amount(ln.net_amount))

    agreement = _sub(tx, "ram:ApplicableHeaderTradeAgreement")
    _party(agreement, "ram:SellerTradeParty", inv.seller)
    _party(agreement, "ram:BuyerTradeParty", inv.buyer)

    delivery = _sub(tx, "ram:ApplicableHeaderTradeDelivery")
    if inv.delivery_address and not inv.delivery_address.is_empty():
        ship = _sub(delivery, "ram:ShipToTradeParty")
        _address(ship, "ram:PostalTradeAddress", inv.delivery_address)

    settlement = _sub(tx, "ram:ApplicableHeaderTradeSettlement")
    _sub(settlement, "ram:InvoiceCurrencyCode", inv.currency)
    if inv.iban:
        means = _sub(settlement, "ram:SpecifiedTradeSettlementPaymentMeans")
        _sub(means, "ram:TypeCode", "58")  # virement SEPA
        acct = _sub(means, "ram:PayeePartyCreditorFinancialAccount")
        _sub(acct, "ram:IBANID", inv.iban)
        if inv.bic:
            inst = _sub(means, "ram:PayeeSpecifiedCreditorFinancialInstitution")
            _sub(inst, "ram:BICID", inv.bic)
    groups = _vat_groups(inv)
    for rate, base, amount in groups:
        tax = _sub(settlement, "ram:ApplicableTradeTax")
        _sub(tax, "ram:CalculatedAmount", _amount(amount))
        _sub(tax, "ram:TypeCode", "VAT")
        if rate == 0:
            _sub(tax, "ram:ExemptionReason", "Exonération de TVA")
        _sub(tax, "ram:BasisAmount", _amount(base))
        _sub(tax, "ram:CategoryCode", "S" if rate > 0 else "Z")
        if inv.vat_on_debits:
            _sub(tax, "ram:DueDateTypeCode", "5")  # exigibilité à la date de facture (débits)
        _sub(tax, "ram:RateApplicablePercent", _rate(rate))
    if inv.due_date or inv.payment_terms:
        terms = _sub(settlement, "ram:SpecifiedTradePaymentTerms")
        if inv.payment_terms:
            _sub(terms, "ram:Description", inv.payment_terms)
        if inv.due_date:
            _date(terms, "ram:DueDateDateTime", inv.due_date)

    line_total = sum((ln.net_amount or Decimal(0) for ln in inv.lines), Decimal(0))
    tax_total = inv.total_vat if inv.total_vat is not None else sum(a for _, _, a in groups)
    basis = inv.total_without_vat if inv.total_without_vat is not None else line_total
    grand = inv.total_with_vat if inv.total_with_vat is not None else basis + tax_total
    summ = _sub(settlement, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    _sub(summ, "ram:LineTotalAmount", _amount(line_total))
    _sub(summ, "ram:TaxBasisTotalAmount", _amount(basis))
    _sub(summ, "ram:TaxTotalAmount", _amount(tax_total), currencyID=inv.currency)
    _sub(summ, "ram:GrandTotalAmount", _amount(grand))
    _sub(
        summ,
        "ram:DuePayableAmount",
        _amount(inv.amount_due if inv.amount_due is not None else grand),
    )

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
