"""Contrôles déterministes des identifiants français et bancaires.

Ces fonctions servent deux fois : pour valider la facture, et pour arbitrer entre
plusieurs candidats pendant l'extraction (un SIREN dont la clé de Luhn est fausse
est presque toujours une erreur d'OCR ou de lecture).
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\D")
LA_POSTE_SIREN = "356000000"  # exception : les SIRET de La Poste ne respectent pas Luhn


def digits_only(value: str | None) -> str:
    return _DIGITS.sub("", value or "")


def luhn_ok(number: str) -> bool:
    if not number.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def is_valid_siren(value: str | None) -> bool:
    siren = digits_only(value)
    return len(siren) == 9 and luhn_ok(siren)


def is_valid_siret(value: str | None) -> bool:
    siret = digits_only(value)
    if len(siret) != 14:
        return False
    if siret.startswith(LA_POSTE_SIREN):
        return sum(int(c) for c in siret) % 5 == 0
    return luhn_ok(siret)


def fr_vat_key(siren: str) -> str:
    """Clé du numéro de TVA intracommunautaire français : (12 + 3 × (SIREN mod 97)) mod 97."""
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def fr_vat_from_siren(siren: str) -> str:
    return f"FR{fr_vat_key(siren)}{siren}"


def normalize_vat_id(value: str | None) -> str:
    return re.sub(r"[\s.\-]", "", value or "").upper()


def is_valid_fr_vat(value: str | None) -> bool:
    vat = normalize_vat_id(value)
    m = re.fullmatch(r"FR([0-9A-Z]{2})(\d{9})", vat)
    if not m:
        return False
    key, siren = m.groups()
    if key.isdigit():
        return key == fr_vat_key(siren)
    return True  # ancien format alphanumérique : pas de clé vérifiable


def vat_matches_siren(vat_id: str | None, siren: str | None) -> bool:
    vat = normalize_vat_id(vat_id)
    return bool(vat.startswith("FR") and siren and vat[-9:] == digits_only(siren))


def normalize_iban(value: str | None) -> str:
    return re.sub(r"\s", "", value or "").upper()


def is_valid_iban(value: str | None) -> bool:
    iban = normalize_iban(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def iban_check_digits(country: str, bban: str) -> str:
    numeric = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{98 - int(numeric) % 97:02d}"


def luhn_complete(partial: str) -> str:
    """Ajoute le chiffre de contrôle de Luhn à une chaîne de chiffres."""
    for d in range(10):
        if luhn_ok(partial + str(d)):
            return partial + str(d)
    raise ValueError(partial)  # pragma: no cover
