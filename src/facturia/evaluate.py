"""Évaluation sur un dossier de factures annotées (`facture.pdf` + `facture.json`).

Le JSON suit le modèle `Invoice`. Une clé optionnelle `_spec.expected_issues` liste les
anomalies de conformité attendues, ce qui permet de mesurer aussi la détection.
Le format est volontairement simple pour pouvoir évaluer sur un jeu réel annoté à la main.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .extract import CORE_FIELDS, TRACKED_FIELDS, get_extractor
from .extract.rules import fold
from .models import Invoice
from .normalize import money
from .pipeline import Decision, process

COMPLIANCE_CODES = [
    "FR-BUYER-SIREN-MISSING", "FR-OPERATION-CATEGORY-MISSING", "FR-NOTE-PENALTIES-MISSING",
    "FR-NOTE-RECOVERY-FEE-MISSING", "FR-NOTE-DISCOUNT-MISSING", "FR-INVOICE-NUMBER-FORMAT",
]  # fmt: skip


FIELD_NAMES = {
    "number": "Numéro de facture",
    "issue_date": "Date d'émission",
    "due_date": "Échéance",
    "seller.name": "Nom du vendeur",
    "seller.siren": "SIREN du vendeur",
    "seller.vat_id": "TVA du vendeur",
    "buyer.name": "Nom du client",
    "buyer.siren": "SIREN du client",
    "buyer.vat_id": "TVA du client",
    "total_without_vat": "Total HT",
    "total_vat": "Total TVA",
    "total_with_vat": "Total TTC",
    "iban": "IBAN",
    "operation_category": "Catégorie d'opération",
    "lines": "Lignes",
}
ISSUE_NAMES = {
    "FR-BUYER-SIREN-MISSING": "SIREN du client absent",
    "FR-OPERATION-CATEGORY-MISSING": "Catégorie d'opération absente",
    "FR-NOTE-PENALTIES-MISSING": "Pénalités de retard absentes",
    "FR-NOTE-RECOVERY-FEE-MISSING": "Indemnité de 40 € absente",
    "FR-NOTE-DISCOUNT-MISSING": "Conditions d'escompte absentes",
    "FR-INVOICE-NUMBER-FORMAT": "Numéro de facture mal formé",
}
DECISION_NAMES = {
    "ready": "Prête à émettre",
    "fix_required": "À corriger",
    "human_review": "Revue humaine",
}
SOURCE_LABELS = {"native": "PDF natifs", "ocr": "Scans", "mixed": "PDF mixtes"}


def _get(inv: Invoice, path: str):
    obj = inv
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def field_match(name: str, pred, gold) -> bool:
    if name == "lines":
        if len(pred) != len(gold):
            return False
        return all(
            p.net_amount is not None
            and money(p.net_amount) == money(g.net_amount)
            and p.quantity == g.quantity
            and fold(" ".join(p.description.split())) == fold(g.description)
            for p, g in zip(pred, gold, strict=True)
        )
    if gold is None or pred is None:
        return gold is None and pred is None
    if name.endswith(".name"):
        return " ".join(fold(pred).split()) == " ".join(fold(gold).split())
    return str(pred) == str(gold)


@dataclass
class EvalResult:
    n_docs: int
    field_accuracy: dict[str, float]
    field_accuracy_by_source: dict[str, dict[str, float]]
    doc_exact: float
    compliance: dict[str, dict[str, float]]
    decisions: dict[str, int]
    latency_ms: dict[str, dict[str, float]]
    silent_errors: int = 0
    reviewed_with_errors: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_markdown(self, title: str = "Résultats") -> str:
        def pct(x: float) -> str:
            return f"{x * 100:.1f} %".replace(".", ",")

        sources = sorted(self.field_accuracy_by_source)
        out = [
            f"## {title}",
            "",
            f"{self.n_docs} factures. Exactitude par champ, en correspondance exacte après normalisation.",
            "",
        ]
        head = (
            "| Champ | Global | "
            + " | ".join(
                f"{SOURCE_LABELS.get(s, s)} ({int(self.field_accuracy_by_source[s]['_n'])})"
                for s in sources
            )
            + " |"
        )
        out += [head, "|" + "---|" * (2 + len(sources))]
        for f in TRACKED_FIELDS:
            row = (
                f"| {FIELD_NAMES[f]} | {pct(self.field_accuracy[f])} | "
                + " | ".join(pct(self.field_accuracy_by_source[s][f]) for s in sources)
                + " |"
            )
            out.append(row)
        out += [
            "",
            f"**Factures extraites sans aucune erreur sur les {len(TRACKED_FIELDS)} champs : "
            f"{pct(self.doc_exact)}**",
            "",
        ]
        out += [
            "### Détection des mentions obligatoires manquantes",
            "",
            "| Anomalie | Précision | Rappel | Cas |",
            "|---|---|---|---|",
        ]
        for code, m in self.compliance.items():
            out.append(
                f"| {ISSUE_NAMES[code]} | {pct(m['precision'])} | {pct(m['recall'])} | {int(m['support'])} |"
            )
        out += [
            "",
            "### Routage et erreurs silencieuses",
            "",
            "| Décision | Factures |",
            "|---|---|",
        ]
        out += [f"| {DECISION_NAMES[k]} | {v} |" for k, v in sorted(self.decisions.items())]
        out += [
            "",
            "Factures avec au moins un champ essentiel faux **non envoyées en revue** "
            f"(erreurs silencieuses) : **{self.silent_errors}** sur {self.n_docs}.",
            "",
            "Factures avec un champ essentiel faux correctement envoyées en revue : "
            f"{self.reviewed_with_errors}.",
        ]
        out += ["", "### Latence (ms, CPU)", "", "| Source | Médiane | p95 |", "|---|---|---|"]
        out += [
            f"| {SOURCE_LABELS.get(s, s)} | {v['p50']:.0f} | {v['p95']:.0f} |"
            for s, v in sorted(self.latency_ms.items())
        ]
        return "\n".join(out) + "\n"


def evaluate(folder: str | Path, extractor: str = "rules", limit: int | None = None) -> EvalResult:
    folder = Path(folder)
    pdfs = sorted(folder.glob("*.pdf"))[:limit]
    ext = get_extractor(extractor)
    hits: dict[str, list[int]] = defaultdict(list)
    hits_src: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    tp, fp, fn, support = (defaultdict(int) for _ in range(4))
    decisions: dict[str, int] = defaultdict(int)
    latency: dict[str, list[float]] = defaultdict(list)
    exact = 0
    silent = reviewed = 0
    errors = []
    for pdf in pdfs:
        gold_raw = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
        spec = gold_raw.pop("_spec", {})
        gold = Invoice.model_validate(gold_raw)
        t = time.perf_counter()
        report = process(pdf, extractor=ext).report
        latency[report.source].append((time.perf_counter() - t) * 1000)
        decisions[report.decision.value] += 1
        all_ok = True
        for f in TRACKED_FIELDS:
            ok = field_match(f, _get(report.invoice, f), _get(gold, f))
            hits[f].append(ok)
            hits_src[report.source][f].append(ok)
            if not ok:
                all_ok = False
                errors.append(
                    {
                        "file": pdf.name,
                        "field": f,
                        "pred": str(_get(report.invoice, f))[:120],
                        "gold": str(_get(gold, f))[:120],
                    }
                )
        exact += all_ok
        core_wrong = any(
            not field_match(f, _get(report.invoice, f), _get(gold, f)) for f in CORE_FIELDS
        )
        if core_wrong:
            if report.decision == Decision.HUMAN_REVIEW:
                reviewed += 1
            else:
                silent += 1
        if "expected_issues" in spec:
            expected = set(spec["expected_issues"])
            found = {i.code for i in report.issues}
            for code in COMPLIANCE_CODES:
                support[code] += code in expected
                tp[code] += code in expected and code in found
                fp[code] += code not in expected and code in found
                fn[code] += code in expected and code not in found

    def rate(xs):
        return sum(xs) / len(xs) if xs else 0.0

    by_src = {}
    for s, d in hits_src.items():
        by_src[s] = {f: rate(v) for f, v in d.items()}
        by_src[s]["_n"] = len(next(iter(d.values())))
    compliance = {}
    for code in COMPLIANCE_CODES:
        p = tp[code] / (tp[code] + fp[code]) if tp[code] + fp[code] else 1.0
        r = tp[code] / (tp[code] + fn[code]) if tp[code] + fn[code] else 1.0
        compliance[code] = {"precision": p, "recall": r, "support": support[code]}
    lat = {
        s: {"p50": statistics.median(v), "p95": sorted(v)[max(0, int(0.95 * len(v)) - 1)]}
        for s, v in latency.items()
    }
    for d in Decision:
        decisions.setdefault(d.value, 0)
    return EvalResult(
        n_docs=len(pdfs),
        field_accuracy={f: rate(v) for f, v in hits.items()},
        field_accuracy_by_source=by_src,
        doc_exact=exact / len(pdfs) if pdfs else 0.0,
        compliance=compliance,
        decisions=dict(decisions),
        latency_ms=lat,
        silent_errors=silent,
        reviewed_with_errors=reviewed,
        errors=errors,
    )
