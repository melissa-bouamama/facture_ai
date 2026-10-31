"""Contrôles de conformité : norme EN 16931, règles françaises (BR-FR) et réforme 2026.

Chaque anomalie référence le champ concerné (BT/BG), la règle officielle quand elle
existe, et l'exposition financière estimée. Les règles d'arithmétique jouent un double
rôle : elles signalent une facture fausse… ou une extraction fausse. C'est pourquoi le
pipeline combine leur résultat avec la confiance d'extraction avant de décider s'il
faut une revue humaine.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from . import identifiers as ids
from .models import Invoice, OperationCategory, Party
from .normalize import money

FINE_PER_MENTION = Decimal("15")  # CGI art. 1737, II
FINE_CAP_RATIO = Decimal("0.25")  # plafond : 25 % du montant de la facture
FR_VAT_RATES = {Decimal(r) for r in ("0", "2.1", "5.5", "10", "20", "0.9", "1.05", "1.75", "8.5",
                                       "13", "7", "9.2", "9.6", "19.6", "20.6")}  # fmt: skip
INVOICE_ID_RE = re.compile(r"^[A-Za-z0-9+\-_/]{1,35}$")
TOLERANCE = Decimal("0.01")

SERVICE_HINTS = re.compile(
    r"prestation|conseil|jour|heure|abonnement|maintenance|formation|licence|audit|support|"
    r"d[eé]veloppement|r[eé]daction|h[eé]bergement|main d|accompagnement|service|mission",
    re.IGNORECASE,
)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str
    field: str | None = None
    bt: str | None = None
    rule: str | None = None
    fine_eur: Decimal | None = None
    suggestion: str | None = None


COMPANY_MARKERS = re.compile(
    r"\b(?:sas|sasu|sarl|eurl|sa|snc|sci|scop|scm|selarl|selas|eirl|gie|sem|soci[eé]t[eé]|"
    r"association|ets|[eé]tablissements?|cabinet|groupe?|holding|ltd|inc|gmbh|llc|bv|spa|srl)\b",
    re.IGNORECASE,
)
CIVILITY = re.compile(r"^(?:m\.|mr\.?|mme|mlle|monsieur|madame|mademoiselle)\s+", re.IGNORECASE)


def buyer_is_individual(buyer: Party) -> bool:
    """Client probablement particulier : aucun identifiant d'entreprise, pas de forme
    juridique, et un nom de personne écrit à la française (« DUPONT Marie », « Mme Dupont »).

    Volontairement prudent : « Marie Dupont » sans majuscules ne suffit pas, et dans le
    doute les règles B2B s'appliquent.
    """
    if not buyer.name or buyer.siren or buyer.siret or buyer.vat_id:
        return False
    name = buyer.name.strip()
    if COMPANY_MARKERS.search(name):
        return False
    if CIVILITY.match(name):
        return True
    words = name.split()
    if not 2 <= len(words) <= 4 or not all(re.fullmatch(r"[A-Za-zÀ-ÿ'’-]+", w) for w in words):
        return False
    family = [w for w in words if len(w) >= 2 and w.isupper()]
    given = [w for w in words if w[0].isupper() and w[1:].islower()]
    return bool(family) and bool(given)


def guess_category(inv: Invoice) -> OperationCategory | None:
    """Propose une catégorie d'opération à partir des libellés de lignes (suggestion seulement)."""
    if not inv.lines:
        return None
    services = sum(1 for ln in inv.lines if SERVICE_HINTS.search(ln.description))
    if services == len(inv.lines):
        return OperationCategory.SERVICES
    if services == 0:
        return OperationCategory.GOODS
    return OperationCategory.MIXED


def _close(a: Decimal, b: Decimal, tol: Decimal = TOLERANCE) -> bool:
    return abs(money(a) - money(b)) <= tol


def validate(inv: Invoice, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    def add(code, severity, message, field=None, bt=None, rule=None, fine=False, suggestion=None):
        issues.append(
            Issue(
                code=code,
                severity=severity,
                message=message,
                field=field,
                bt=bt,
                rule=rule,
                fine_eur=FINE_PER_MENTION if fine else None,
                suggestion=suggestion,
            )
        )

    E, W, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
    # Client particulier : la facture électronique obligatoire et les mentions du Code de
    # commerce (L441-9) ne concernent que les échanges entre professionnels.
    b2c = buyer_is_individual(inv.buyer)

    # --- identification de la facture
    if not inv.number:
        add(
            "CORE-NUMBER-MISSING",
            E,
            "Numéro de facture absent.",
            "number",
            "BT-1",
            "BR-02",
            fine=True,
        )
    elif not INVOICE_ID_RE.match(inv.number):
        fixed = re.sub(r"[^A-Za-z0-9+\-_/]+", "-", inv.number.strip())[:35]
        add(
            "FR-INVOICE-NUMBER-FORMAT",
            E,
            f"Le numéro « {inv.number} » contient des caractères refusés (espaces, points…) "
            "ou dépasse 35 caractères : la plateforme agréée rejettera la facture.",
            "number",
            "BT-1",
            "BR-FR-01/02",
            suggestion=fixed,
        )
    if inv.type_code not in {"380", "381", "384", "386", "389", "393", "396", "500", "501",
                             "502", "503", "261", "262", "471", "472", "473"}:  # fmt: skip
        add(
            "FR-TYPE-CODE",
            E,
            f"Type de document {inv.type_code} non accepté.",
            "type_code",
            "BT-3",
            "BR-FR-04",
        )

    if inv.issue_date is None:
        add(
            "CORE-ISSUE-DATE-MISSING",
            E,
            "Date d'émission absente.",
            "issue_date",
            "BT-2",
            "BR-03",
            fine=True,
        )
    else:
        if inv.issue_date > today:
            add("DATE-IN-FUTURE", W, "Date d'émission dans le futur.", "issue_date", "BT-2")
        if not 2000 <= inv.issue_date.year <= 2099:
            add(
                "FR-DATE-YEAR",
                E,
                "Année hors de la plage 2000–2099.",
                "issue_date",
                "BT-2",
                "BR-FR-03",
            )
        if inv.due_date and inv.due_date < inv.issue_date:
            add(
                "DUE-BEFORE-ISSUE",
                E,
                "Échéance antérieure à la date d'émission.",
                "due_date",
                "BT-9",
            )

    # --- vendeur
    s = inv.seller
    if not s.name:
        add(
            "CORE-SELLER-NAME-MISSING",
            E,
            "Raison sociale du vendeur absente.",
            "seller.name",
            "BT-27",
            "BR-06",
            fine=True,
        )
    if not s.siren:
        add(
            "FR-SELLER-SIREN-MISSING",
            E,
            "SIREN du vendeur absent.",
            "seller.siren",
            "BT-30",
            "BR-FR-10",
            fine=True,
        )
    elif not ids.is_valid_siren(s.siren):
        add(
            "FR-SELLER-SIREN-INVALID",
            E,
            f"SIREN vendeur {s.siren} invalide (clé de Luhn).",
            "seller.siren",
            "BT-30",
            "BR-FR-10",
            fine=True,
        )
    if s.siret and not ids.is_valid_siret(s.siret):
        n = len(ids.digits_only(s.siret))
        add(
            "FR-SELLER-SIRET-INVALID",
            W,
            f"SIRET du vendeur {s.siret} invalide : "
            + (f"{n} chiffres au lieu de 14." if n != 14 else "clé de contrôle incorrecte."),
            "seller.siret",
            "BT-29",
        )
    if s.siret and s.siren and ids.digits_only(s.siret)[:9] != s.siren:
        add(
            "FR-SELLER-SIRET-INCOHERENT",
            E,
            "Le SIRET ne commence pas par le SIREN.",
            "seller.siret",
            "BT-29",
            "BR-FR-09",
        )
    taxed = any(vb.rate > 0 for vb in inv.vat_breakdown) or (inv.total_vat or 0) > 0
    if not s.vat_id:
        if taxed:
            add(
                "SELLER-VAT-MISSING",
                E,
                "Numéro de TVA intracommunautaire du vendeur absent.",
                "seller.vat_id",
                "BT-31",
                "BR-S-02",
                fine=True,
            )
    elif s.vat_id.startswith("FR"):
        if not ids.is_valid_fr_vat(s.vat_id):
            add(
                "SELLER-VAT-INVALID",
                E,
                f"Clé du numéro de TVA {s.vat_id} incorrecte.",
                "seller.vat_id",
                "BT-31",
                fine=True,
            )
        elif s.siren and not ids.vat_matches_siren(s.vat_id, s.siren):
            add(
                "SELLER-VAT-SIREN-MISMATCH",
                W,
                "Le numéro de TVA ne correspond pas au SIREN du vendeur.",
                "seller.vat_id",
                "BT-31",
            )

    # --- acheteur
    b = inv.buyer
    if not b.name:
        add(
            "CORE-BUYER-NAME-MISSING",
            E,
            "Nom de l'acheteur absent.",
            "buyer.name",
            "BT-44",
            "BR-07",
            fine=True,
        )
    if not b.siren and b2c:
        add(
            "B2C-BUYER-INDIVIDUAL",
            W,
            "Client apparemment particulier : nom de personne, ni SIREN ni forme juridique. "
            "La facture électronique obligatoire ne concerne que les échanges entre entreprises, "
            "donc le SIREN du client, la catégorie d'opération et les mentions de pénalités ne "
            "sont pas exigés. Si le client est une entreprise, ajoutez son SIREN.",
            "buyer.siren",
            "BT-47",
        )
    elif not b.siren:
        add(
            "FR-BUYER-SIREN-MISSING",
            E,
            "SIREN du client absent : nouvelle mention obligatoire pour les factures B2B domestiques.",
            "buyer.siren",
            "BT-47",
            "BR-FR-11",
            fine=True,
        )
    elif not ids.is_valid_siren(b.siren):
        add(
            "FR-BUYER-SIREN-INVALID",
            E,
            f"SIREN client {b.siren} invalide (clé de Luhn).",
            "buyer.siren",
            "BT-47",
            "BR-FR-11",
            fine=True,
        )
    if b.vat_id and b.vat_id.startswith("FR") and not ids.is_valid_fr_vat(b.vat_id):
        add(
            "BUYER-VAT-INVALID",
            W,
            f"Clé du numéro de TVA client {b.vat_id} incorrecte.",
            "buyer.vat_id",
            "BT-48",
        )

    # --- nouvelles mentions 2026
    if inv.operation_category is None and not b2c:
        guess = guess_category(inv)
        add(
            "FR-OPERATION-CATEGORY-MISSING",
            E,
            "Catégorie d'opération absente (livraison de biens, prestation de services ou mixte).",
            "operation_category",
            "BT-23",
            "BR-FR-08",
            fine=True,
            suggestion=f"{guess.label}, code {guess.value}" if guess else None,
        )
    goods = inv.operation_category in (OperationCategory.GOODS, OperationCategory.MIXED) or (
        inv.operation_category is None
        and guess_category(inv) in (OperationCategory.GOODS, OperationCategory.MIXED)
    )
    if goods and inv.delivery_address is None:
        add(
            "FR-DELIVERY-ADDRESS-CHECK",
            INFO,
            "Livraison de biens sans adresse de livraison : obligatoire si elle diffère de l'adresse de facturation.",
            "delivery_address",
            "BG-15",
        )
    if (
        inv.operation_category in (OperationCategory.SERVICES, OperationCategory.MIXED)
        and not inv.vat_on_debits
    ):
        add(
            "FR-VAT-DEBITS-CHECK",
            INFO,
            "Si le vendeur a opté pour le paiement de la TVA d'après les débits, la mention doit figurer sur la facture.",
            "vat_on_debits",
            "BT-8",
        )

    # --- mentions légales B2B (Code de commerce L441-9, notes PMD/PMT/AAB)
    if not b2c and not inv.late_penalty_note:
        add(
            "FR-NOTE-PENALTIES-MISSING",
            E,
            "Taux des pénalités de retard non mentionné.",
            "late_penalty_note",
            "BT-22",
            "BR-FR-05 (PMD)",
        )
    if not b2c and not inv.recovery_fee_note:
        add(
            "FR-NOTE-RECOVERY-FEE-MISSING",
            E,
            "Indemnité forfaitaire de 40 € pour frais de recouvrement non mentionnée.",
            "recovery_fee_note",
            "BT-22",
            "BR-FR-05 (PMT)",
        )
    if not b2c and not inv.discount_note:
        add(
            "FR-NOTE-DISCOUNT-MISSING",
            E,
            "Conditions d'escompte non mentionnées (même « pas d'escompte »).",
            "discount_note",
            "BT-22",
            "BR-FR-05 (AAB)",
        )

    # --- montants
    if not inv.lines:
        add("CORE-NO-LINES", E, "Aucune ligne de facture.", "lines", "BG-25", "BR-16")
    for k, ln in enumerate(inv.lines, start=1):
        if (
            ln.unit_price is not None
            and ln.net_amount is not None
            and not _close(ln.quantity * ln.unit_price, ln.net_amount)
        ):
            add(
                "LINE-ARITHMETIC",
                W,
                f"Ligne {k} : quantité × prix unitaire ≠ montant.",
                f"lines[{k}]",
                "BT-131",
            )
        if ln.vat_rate is not None and ln.vat_rate not in FR_VAT_RATES:
            add(
                "FR-VAT-RATE-INVALID",
                E,
                f"Ligne {k} : taux de TVA {ln.vat_rate} % non autorisé en France.",
                f"lines[{k}]",
                "BT-152",
                "BR-FR-16",
            )
    missing = [
        n
        for n, v in (
            ("HT", inv.total_without_vat),
            ("TVA", inv.total_vat),
            ("TTC", inv.total_with_vat),
        )
        if v is None
    ]
    if missing:
        add(
            "CORE-TOTALS-MISSING",
            E,
            f"Totaux absents : {', '.join(missing)}.",
            "totals",
            "BT-109/110/112",
            "BR-12/13/14",
            fine=True,
        )
    else:
        if not _close(inv.total_without_vat + inv.total_vat, inv.total_with_vat):
            add(
                "TOTALS-UNBALANCED",
                E,
                f"HT + TVA ≠ TTC ({inv.total_without_vat} + {inv.total_vat} ≠ {inv.total_with_vat}).",
                "totals",
                "BT-112",
                "BR-CO-15",
            )
        if inv.lines and all(ln.net_amount is not None for ln in inv.lines):
            lines_sum = sum(ln.net_amount for ln in inv.lines)
            if not _close(lines_sum, inv.total_without_vat):
                add(
                    "LINES-SUM-MISMATCH",
                    E,
                    f"Somme des lignes ({money(lines_sum)}) ≠ total HT ({inv.total_without_vat}).",
                    "total_without_vat",
                    "BT-106",
                    "BR-CO-10",
                )
        if inv.vat_breakdown:
            tax_sum = sum(vb.tax_amount for vb in inv.vat_breakdown)
            if not _close(tax_sum, inv.total_vat):
                add(
                    "VAT-BREAKDOWN-MISMATCH",
                    E,
                    "La somme de la TVA par taux ne correspond pas au total de TVA.",
                    "total_vat",
                    "BT-110",
                    "BR-CO-14",
                )
            for vb in inv.vat_breakdown:
                if vb.rate not in FR_VAT_RATES:
                    add(
                        "FR-VAT-RATE-INVALID",
                        E,
                        f"Taux de TVA {vb.rate} % non autorisé en France.",
                        "vat_breakdown",
                        "BT-119",
                        "BR-FR-16",
                    )
                expected = money(vb.taxable_amount * vb.rate / 100)
                if not _close(expected, vb.tax_amount, Decimal("0.02")):
                    add(
                        "VAT-CALCULATION",
                        W,
                        f"TVA à {vb.rate} % : {vb.tax_amount} trouvé, {expected} attendu.",
                        "vat_breakdown",
                        "BT-117",
                        "BR-S-09",
                    )
    if (
        inv.amount_due is not None
        and inv.total_with_vat is not None
        and inv.amount_due > inv.total_with_vat + TOLERANCE
    ):
        add(
            "AMOUNT-DUE-EXCEEDS-TOTAL",
            W,
            "Le net à payer dépasse le total TTC.",
            "amount_due",
            "BT-115",
        )
    if inv.iban and not ids.is_valid_iban(inv.iban):
        add("IBAN-INVALID", W, "IBAN invalide (clé mod 97).", "iban", "BT-84")
    return issues


def fine_exposure(issues: list[Issue], inv: Invoice) -> Decimal:
    """Amende potentielle pour mentions manquantes ou erronées, plafonnée à 25 % du TTC."""
    total = sum((i.fine_eur for i in issues if i.fine_eur), Decimal(0))
    if inv.total_with_vat:
        total = min(total, money(abs(inv.total_with_vat) * FINE_CAP_RATIO))
    return money(total)
