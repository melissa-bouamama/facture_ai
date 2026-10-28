"""Interface commune aux extracteurs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import FieldConfidence, Invoice
from ..reader import Document

# Champs suivis individuellement pour la confiance et l'évaluation.
TRACKED_FIELDS = [
    "number", "issue_date", "due_date",
    "seller.name", "seller.siren", "seller.vat_id",
    "buyer.name", "buyer.siren", "buyer.vat_id",
    "total_without_vat", "total_vat", "total_with_vat",
    "iban", "operation_category", "lines",
]  # fmt: skip

# Champs sans lesquels aucune facture n'est exploitable : ils pilotent la confiance globale.
# Les mentions optionnelles ou propres à 2026 (SIREN client, catégorie…) sont jugées par
# la validation, pas par la confiance : leur absence est une anomalie, pas une incertitude.
CORE_FIELDS = [
    "number", "issue_date", "seller.name", "seller.siren", "buyer.name",
    "total_without_vat", "total_vat", "total_with_vat", "lines",
]  # fmt: skip


@dataclass
class Extraction:
    invoice: Invoice
    confidence: dict[str, FieldConfidence] = field(default_factory=dict)
    backend: str = "rules"
    notes: list[str] = field(default_factory=list)

    def set(self, name: str, value: float, source: str) -> None:
        self.confidence[name] = FieldConfidence(value=round(value, 3), source=source)

    def score(self, name: str) -> float:
        fc = self.confidence.get(name)
        return fc.value if fc else 0.0

    @property
    def mean_confidence(self) -> float:
        values = [self.score(f) for f in CORE_FIELDS]
        return sum(values) / len(values)


class Extractor(Protocol):
    name: str

    def extract(self, doc: Document) -> Extraction: ...
