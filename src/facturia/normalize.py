"""Normalisation des montants et des dates au format français."""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONTHS = {
    "janvier": 1, "janv": 1, "février": 2, "fevrier": 2, "févr": 2, "fevr": 2, "mars": 3,
    "avril": 4, "avr": 4, "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "août": 8,
    "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10, "novembre": 11,
    "nov": 11, "décembre": 12, "decembre": 12, "déc": 12, "dec": 12,
}  # fmt: skip

AMOUNT_RE = re.compile(r"(?<![\w.,])-?(?:\d{1,3}(?:[   .]\d{3})+|\d+)(?:[.,]\d{1,2})?(?![\d])")
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")
DATE_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})(?:er)?\s+("
    + "|".join(sorted(MONTHS, key=len, reverse=True))
    + r")\.?\s+(\d{4})\b",
    re.IGNORECASE,
)
CENT = Decimal("0.01")


def parse_amount(text: str | None) -> Decimal | None:
    """Convertit « 1 234,56 € », « 1.234,56 » ou « 1234.56 » en Decimal."""
    if text is None:
        return None
    s = re.sub(r"[€\s  ]|EUR", "", str(text), flags=re.IGNORECASE)
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    elif s.count(".") >= 1:
        head, _, tail = s.rpartition(".")
        thousands = len(tail) == 3 and head  # « 1.234 » : séparateur de milliers
        s = s.replace(".", "") if thousands else head.replace(".", "") + "." + tail
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def find_amounts(text: str) -> list[Decimal]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        v = parse_amount(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _safe_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[date]:
    """Renvoie les dates trouvées dans l'ordre d'apparition."""
    found: list[tuple[int, date]] = []
    for m in DATE_ISO_RE.finditer(text):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append((m.start(), d))
    for m in DATE_NUMERIC_RE.finditer(text):
        d = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            found.append((m.start(), d))
    for m in DATE_TEXT_RE.finditer(text):
        month = MONTHS.get(m.group(2).lower().rstrip("."))
        d = _safe_date(int(m.group(3)), month, int(m.group(1))) if month else None
        if d:
            found.append((m.start(), d))
    return [d for _, d in sorted(found, key=lambda x: x[0])]


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    dates = find_dates(str(text))
    return dates[0] if dates else None


def parse_rate(text: str | None) -> Decimal | None:
    if text is None:
        return None
    m = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", str(text))
    raw = m.group(1) if m else str(text).strip().rstrip("%")
    try:
        return Decimal(raw.replace(",", ".")).normalize()
    except InvalidOperation:
        return None


def fmt_amount(value: Decimal | None) -> str:
    """Format français lisible : 1 234,56."""
    if value is None:
        return "absent"
    q = money(value)
    sign = "-" if q < 0 else ""
    integer, _, frac = f"{abs(q):.2f}".partition(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}{' '.join(groups)},{frac}"
