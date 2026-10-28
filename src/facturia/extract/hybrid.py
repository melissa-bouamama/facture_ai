"""Mode hybride : règles d'abord, LLM seulement quand la validation révèle un doute.

Le coût d'un LLM n'est justifié que sur les factures difficiles. On lance donc
l'extracteur à règles (≈ quelques ms), puis on décide d'escalader si :
- un champ indispensable manque ou a une confiance faible,
- l'arithmétique ne tombe pas juste (HT + TVA ≠ TTC, somme des lignes ≠ HT…),
  signe probable d'une erreur de lecture plutôt que d'une facture fausse,
- (option) une mention obligatoire semble absente : on demande une seconde lecture
  avant d'accuser la facture d'être non conforme.

La fusion se fait champ par champ : on garde la valeur qui passe les contrôles
(clés, ancrage, arithmétique), et à défaut celle de plus forte confiance.
"""

from __future__ import annotations

import logging

from ..models import Invoice
from ..normalize import money
from ..reader import Document
from ..validate import validate
from .base import CORE_FIELDS, Extraction, label
from .llm import LLMExtractor
from .rules import RulesExtractor

log = logging.getLogger(__name__)

ARITH_CODES = {
    "TOTALS-UNBALANCED",
    "LINES-SUM-MISMATCH",
    "VAT-BREAKDOWN-MISMATCH",
    "CORE-TOTALS-MISSING",
    "CORE-NO-LINES",
}
MENTION_CODES = {"FR-BUYER-SIREN-MISSING", "FR-OPERATION-CATEGORY-MISSING", "FR-NOTE-PENALTIES-MISSING",
                 "FR-NOTE-RECOVERY-FEE-MISSING", "FR-NOTE-DISCOUNT-MISSING"}  # fmt: skip
SIMPLE_FIELDS = ["number", "issue_date", "due_date", "iban", "bic", "operation_category", "payment_terms",
                 "late_penalty_note", "recovery_fee_note", "discount_note", "delivery_address"]  # fmt: skip
PARTY_FIELDS = ["name", "siren", "siret", "vat_id"]


MENTION_LABELS = {
    "FR-BUYER-SIREN-MISSING": "SIREN du client",
    "FR-OPERATION-CATEGORY-MISSING": "catégorie d'opération",
    "FR-NOTE-PENALTIES-MISSING": "pénalités de retard",
    "FR-NOTE-RECOVERY-FEE-MISSING": "indemnité de 40 €",
    "FR-NOTE-DISCOUNT-MISSING": "conditions d'escompte",
}
ARITH_LABELS = {
    "TOTALS-UNBALANCED": "HT plus TVA différent du TTC",
    "LINES-SUM-MISMATCH": "somme des lignes différente du total HT",
    "VAT-BREAKDOWN-MISMATCH": "TVA par taux différente du total",
    "CORE-TOTALS-MISSING": "totaux absents",
    "CORE-NO-LINES": "aucune ligne lue",
}


def escalation_reasons(
    ex: Extraction, check_mentions: bool = True, threshold: float = 0.75
) -> list[str]:
    weak = [label(f) for f in CORE_FIELDS if ex.score(f) < threshold]
    codes = {i.code for i in validate(ex.invoice)}
    reasons = []
    if weak:
        reasons.append("lecture peu sûre : " + ", ".join(weak))
    arith = sorted(codes & ARITH_CODES)
    if arith:
        reasons.append("montants incohérents : " + ", ".join(ARITH_LABELS[c] for c in arith))
    if check_mentions:
        mentions = sorted(codes & MENTION_CODES)
        if mentions:
            reasons.append(
                "mentions à confirmer : " + ", ".join(MENTION_LABELS[c] for c in mentions)
            )
    return reasons


def _totals_consistent(inv: Invoice) -> bool:
    if None in (inv.total_without_vat, inv.total_vat, inv.total_with_vat) or not inv.lines:
        return False
    if any(ln.net_amount is None for ln in inv.lines):
        return False
    return money(inv.total_without_vat + inv.total_vat) == money(inv.total_with_vat) and money(
        sum(ln.net_amount for ln in inv.lines)
    ) == money(inv.total_without_vat)


def merge(rules: Extraction, llm: Extraction) -> Extraction:
    a, b = rules.invoice, llm.invoice
    out = a.model_copy(deep=True)
    ex = Extraction(
        invoice=out,
        confidence=dict(rules.confidence),
        backend="hybrid",
        notes=rules.notes + llm.notes,
    )

    def take(field: str, source_obj, target_obj, attr: str):
        setattr(target_obj, attr, getattr(source_obj, attr))
        if field in llm.confidence:
            ex.confidence[field] = llm.confidence[field].model_copy(update={"source": "hybrid:llm"})

    def arbitrate(field: str, va, vb, source_obj, target_obj, attr: str):
        if vb is None:
            return
        if va == vb:  # deux lectures indépendantes concordent : confiance renforcée
            base = max(rules.score(field), llm.score(field))
            ex.set(field, min(0.99, base + 0.1), "hybrid:agree")
        elif va is None or llm.score(field) >= rules.score(field):
            # désaccord : l'escalade signale déjà un doute sur les règles, le LLM l'emporte à égalité
            take(field, source_obj, target_obj, attr)

    for f in SIMPLE_FIELDS:
        arbitrate(f, getattr(a, f), getattr(b, f), b, out, f)
    out.vat_on_debits = a.vat_on_debits or b.vat_on_debits
    for role in ("seller", "buyer"):
        pa, pb, po = getattr(a, role), getattr(b, role), getattr(out, role)
        for f in PARTY_FIELDS:
            arbitrate(f"{role}.{f}", getattr(pa, f), getattr(pb, f), pb, po, f)
        if po.address.is_empty() and not pb.address.is_empty():
            po.address = pb.address
    # montants et lignes : on garde le bloc cohérent, en bloc (pas de mélange)
    if not _totals_consistent(a) and _totals_consistent(b):
        for f in (
            "total_without_vat",
            "total_vat",
            "total_with_vat",
            "amount_due",
            "lines",
            "vat_breakdown",
        ):
            take(f, b, out, f)
    return ex


class HybridExtractor:
    name = "hybrid"

    def __init__(self, llm: LLMExtractor | None = None, check_mentions: bool = True):
        self.rules = RulesExtractor()
        self.llm = llm or LLMExtractor()
        self.check_mentions = check_mentions
        self.llm_calls = 0

    def extract(self, doc: Document) -> Extraction:
        first = self.rules.extract(doc)
        reasons = escalation_reasons(first, self.check_mentions)
        if not reasons:
            first.backend = "hybrid:rules-only"
            return first
        log.info("escalade vers le LLM : %s", ". ".join(reasons))
        try:
            second = self.llm.extract(doc)
            self.llm_calls += 1
        except Exception as exc:  # le LLM est un bonus, jamais un point de rupture
            first.notes.append(
                f"LLM indisponible ({type(exc).__name__}), résultat des règles conservé."
            )
            first.backend = "hybrid:rules-fallback"
            return first
        merged = merge(first, second)
        merged.notes.append(
            "Appel au LLM. " + ". ".join(r[0].upper() + r[1:] for r in reasons) + "."
        )
        return merged
