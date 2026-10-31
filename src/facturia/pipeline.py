"""Pipeline complet : PDF, lecture ou OCR, extraction, validation, décision, Factur-X.

La décision finale sert à router chaque facture :
- prête : extraction sûre et facture conforme, transmissible à la plateforme agréée.
- à corriger : extraction sûre mais mentions manquantes ou montants faux. Il faut
  corriger la facture chez l'émetteur, et les anomalies disent quoi et où.
- revue humaine : doute sur la lecture elle même (confiance faible, ou incohérence
  arithmétique qui peut venir de l'OCR autant que de la facture).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from .extract import CORE_FIELDS, Extractor, get_extractor
from .extract.base import label
from .models import FieldConfidence, Invoice
from .reader import read_pdf
from .validate import Issue, Severity, buyer_is_individual, fine_exposure, validate

REVIEW_THRESHOLD = 0.8
FIELD_FLOOR = 0.6
ARITHMETIC = {
    "TOTALS-UNBALANCED",
    "LINES-SUM-MISMATCH",
    "VAT-BREAKDOWN-MISMATCH",
    "LINE-ARITHMETIC",
    "VAT-CALCULATION",
}


class Decision(str, Enum):
    READY = "ready"
    FIX_REQUIRED = "fix_required"
    HUMAN_REVIEW = "human_review"


class Report(BaseModel):
    file: str | None = None
    source: str
    backend: str
    invoice: Invoice
    confidence: dict[str, FieldConfidence] = Field(default_factory=dict)
    mean_confidence: float
    issues: list[Issue] = Field(default_factory=list)
    fine_exposure_eur: Decimal
    decision: Decision
    decision_reasons: list[str] = Field(default_factory=list)
    xml_valid: bool | None = None
    xml_failures: list[dict] = Field(default_factory=list)
    schematrons_run: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]


@dataclass
class Result:
    report: Report
    xml: bytes | None = None
    facturx_pdf: bytes | None = None


ARITHMETIC_LABELS = {
    "TOTALS-UNBALANCED": "HT plus TVA différent du TTC",
    "LINES-SUM-MISMATCH": "somme des lignes différente du total HT",
    "VAT-BREAKDOWN-MISMATCH": "TVA par taux différente du total de TVA",
    "LINE-ARITHMETIC": "quantité fois prix unitaire différent du montant d'une ligne",
    "VAT-CALCULATION": "montant de TVA incohérent avec le taux",
}


def decide(
    mean_conf: float, confidence: dict[str, FieldConfidence], issues: list[Issue]
) -> tuple[Decision, list[str]]:
    """Choisit la suite à donner et l'explique en phrases lisibles."""
    reasons = []
    if mean_conf < REVIEW_THRESHOLD:
        reasons.append(
            f"Confiance moyenne de {mean_conf * 100:.0f} %, sous le seuil de {REVIEW_THRESHOLD * 100:.0f} %."
        )
    weak = [
        f
        for f in CORE_FIELDS
        if (confidence.get(f).value if f in confidence else 0.0) < FIELD_FLOOR
    ]
    if weak:
        reasons.append("Lecture incertaine ou absente : " + ", ".join(label(f) for f in weak) + ".")
    arith = sorted({i.code for i in issues} & ARITHMETIC)
    if arith:
        reasons.append(
            "Montants incohérents, erreur de lecture ou de facture : "
            + ", ".join(ARITHMETIC_LABELS[c] for c in arith)
            + "."
        )
    if reasons:
        return Decision.HUMAN_REVIEW, reasons
    errors = [i for i in issues if i.severity == Severity.ERROR]
    if errors:
        plural = "s" if len(errors) > 1 else ""
        return Decision.FIX_REQUIRED, [
            f"{len(errors)} anomalie{plural} bloquante{plural} à corriger chez l'émetteur."
        ]
    return Decision.READY, ["Lecture sûre et aucune anomalie bloquante."]


def process(
    pdf: str | Path | bytes,
    extractor: str | Extractor = "rules",
    facturx: bool = False,
    schematron: bool = False,
    force_ocr: bool = False,
    build_xml: bool = False,
) -> Result:
    """Traite une facture PDF et renvoie le rapport (et, sur demande, le XML et le PDF Factur-X)."""
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    pdf_bytes = pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes()
    doc = read_pdf(pdf_bytes, force_ocr=force_ocr)
    timings["read"] = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    ext = get_extractor(extractor) if isinstance(extractor, str) else extractor
    ex = ext.extract(doc)
    timings["extract"] = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    issues = validate(ex.invoice)
    decision, reasons = decide(ex.mean_confidence, ex.confidence, issues)
    timings["validate"] = (time.perf_counter() - t2) * 1000

    report = Report(
        file=None if isinstance(pdf, bytes) else str(pdf),
        source=doc.source,
        backend=ex.backend,
        invoice=ex.invoice,
        confidence=ex.confidence,
        mean_confidence=round(ex.mean_confidence, 3),
        issues=issues,
        fine_exposure_eur=fine_exposure(issues, ex.invoice),
        decision=decision,
        decision_reasons=reasons,
        notes=ex.notes,
    )
    result = Result(report=report)

    if facturx or schematron or build_xml:
        from .export.cii import ExportError, build_cii

        t3 = time.perf_counter()
        try:
            result.xml = build_cii(ex.invoice)
        except ExportError as exc:
            report.notes.append(str(exc))
        if result.xml is not None:
            from .export.schematron import check_xml

            # Les règles BR-FR encadrent la facturation électronique entre entreprises :
            # pour un client particulier, seul le socle européen EN 16931 s'applique.
            which = ("en16931",) if buyer_is_individual(ex.invoice.buyer) else ("en16931", "br-fr")
            if schematron and len(which) == 1:
                report.notes.append(
                    "Client particulier : le XML est vérifié selon la norme EN 16931, les règles "
                    "françaises BR-FR ne visant que les factures entre entreprises."
                )
            xml_report = check_xml(result.xml, schematron=schematron, which=which)
            report.xml_valid = xml_report.valid if schematron else xml_report.xsd_valid
            report.xml_failures = xml_report.failures
            report.schematrons_run = xml_report.schematron_run
            if xml_report.xsd_error:
                report.notes.append("XSD : " + xml_report.xsd_error)
            if facturx and xml_report.xsd_valid:
                from .export.pdf import embed_facturx

                result.facturx_pdf = embed_facturx(pdf_bytes, result.xml, ex.invoice)
        timings["export"] = (time.perf_counter() - t3) * 1000

    timings["total"] = (time.perf_counter() - t0) * 1000
    report.timings_ms = {k: round(v, 1) for k, v in timings.items()}
    return result
