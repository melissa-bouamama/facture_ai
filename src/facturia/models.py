"""Modèle de données d'une facture, aligné sur la norme EN 16931.

Chaque champ porte en commentaire le « Business Term » (BT) ou « Business Group » (BG)
correspondant de la norme, ce qui permet de relier une anomalie détectée à la règle
officielle et de produire le XML Factur-X sans table de correspondance cachée.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class OperationCategory(str, Enum):
    """Catégorie d'opération, nouvelle mention obligatoire depuis la réforme 2026."""

    GOODS = "LB"  # livraison de biens
    SERVICES = "PS"  # prestation de services
    MIXED = "LBPS"  # opération mixte

    @property
    def billing_mode(self) -> str:
        """Cadre de facturation (BT-23) pour un dépôt de facture simple."""
        return {"LB": "B1", "PS": "S1", "LBPS": "M1"}[self.value]

    @property
    def label(self) -> str:
        return {
            "LB": "Livraison de biens",
            "PS": "Prestation de services",
            "LBPS": "Opération mixte (biens et services)",
        }[self.value]


class Address(BaseModel):
    line1: str | None = None  # BT-35 / BT-50 / BT-75
    line2: str | None = None  # BT-36 / BT-51 / BT-76
    postcode: str | None = None  # BT-38 / BT-53 / BT-78
    city: str | None = None  # BT-37 / BT-52 / BT-77
    country_code: str = "FR"  # BT-40 / BT-55 / BT-80

    def is_empty(self) -> bool:
        return not any([self.line1, self.postcode, self.city])

    def one_line(self) -> str:
        parts = [self.line1, self.line2, " ".join(p for p in [self.postcode, self.city] if p)]
        return ", ".join(p for p in parts if p)


class Party(BaseModel):
    name: str | None = None  # BT-27 (vendeur) / BT-44 (acheteur)
    siren: str | None = None  # BT-30 / BT-47, schemeID 0002
    siret: str | None = None  # BT-29 / BT-46, schemeID 0009
    vat_id: str | None = None  # BT-31 / BT-48
    address: Address = Field(default_factory=Address)  # BG-5 / BG-8
    email: str | None = None


class InvoiceLine(BaseModel):
    description: str  # BT-153
    quantity: Decimal = Decimal("1")  # BT-129
    unit_price: Decimal | None = None  # BT-146
    net_amount: Decimal | None = None  # BT-131
    vat_rate: Decimal | None = None  # BT-152
    unit_code: str = "C62"  # BT-130 (C62 = unité)


class VatBreakdown(BaseModel):
    """Ventilation de TVA par taux (BG-23)."""

    rate: Decimal  # BT-119
    taxable_amount: Decimal  # BT-116
    tax_amount: Decimal  # BT-117
    category: str = "S"  # BT-118 (S = taux standard)


class Invoice(BaseModel):
    number: str | None = None  # BT-1
    type_code: str = "380"  # BT-3 (380 facture, 381 avoir)
    issue_date: date | None = None  # BT-2
    due_date: date | None = None  # BT-9
    currency: str = "EUR"  # BT-5

    seller: Party = Field(default_factory=Party)  # BG-4
    buyer: Party = Field(default_factory=Party)  # BG-7
    delivery_address: Address | None = None  # BG-15

    operation_category: OperationCategory | None = None  # BT-23 (cadre de facturation)
    vat_on_debits: bool = False  # option « TVA sur les débits » (BT-8)

    lines: list[InvoiceLine] = Field(default_factory=list)  # BG-25
    vat_breakdown: list[VatBreakdown] = Field(default_factory=list)  # BG-23

    total_without_vat: Decimal | None = None  # BT-109
    total_vat: Decimal | None = None  # BT-110
    total_with_vat: Decimal | None = None  # BT-112
    amount_due: Decimal | None = None  # BT-115

    iban: str | None = None  # BT-84
    bic: str | None = None  # BT-86
    payment_terms: str | None = None  # BT-20

    # Mentions légales B2B (Code de commerce L441-9), portées en notes BG-1
    late_penalty_note: str | None = None  # SubjectCode PMD
    recovery_fee_note: str | None = None  # SubjectCode PMT
    discount_note: str | None = None  # SubjectCode AAB


class FieldConfidence(BaseModel):
    """Confiance attribuée à un champ extrait, entre 0 et 1, et méthode d'obtention."""

    value: float
    source: str  # ex. "rules:label", "rules:fallback", "llm"
