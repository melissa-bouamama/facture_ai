import pytest

from facturia import identifiers as ids
from facturia.extract.rules import repair_ocr_ids


@pytest.mark.parametrize(
    "siren,ok", [("732829320", True), ("732829321", False), ("418273645", True), ("12345", False)]
)
def test_siren_luhn(siren, ok):
    assert ids.is_valid_siren(siren) is ok


def test_siret_and_la_poste_exception():
    assert ids.is_valid_siret("73282932000074")
    assert not ids.is_valid_siret("73282932000075")
    assert ids.is_valid_siret("35600000000001")  # La Poste : somme des chiffres multiple de 5


def test_vat_key_matches_siren():
    assert ids.fr_vat_from_siren("732829320") == "FR44732829320"
    assert ids.is_valid_fr_vat("FR 44 732 829 320")
    assert not ids.is_valid_fr_vat("FR45732829320")
    assert ids.vat_matches_siren("FR44732829320", "732829320")


def test_iban_mod97():
    assert ids.is_valid_iban("FR76 3000 6000 0112 3456 7890 189")
    assert not ids.is_valid_iban("FR76 3000 6000 0112 3456 7890 188")
    bban = "30006000011234567890189"
    assert ids.is_valid_iban("FR" + ids.iban_check_digits("FR", bban) + bban)


def test_ocr_repair_only_when_checksum_confirms():
    # « O » lu à la place de « 0 » dans la clé de TVA : corrigé car la clé devient valide
    assert repair_ocr_ids("N° TVA FRO7552813248") == "N° TVA FR07552813248"
    # « l » à la place de « 1 » dans un SIREN valide
    assert repair_ocr_ids("SIREN 4l8273645") == "SIREN 418273645"
    # chaîne qui ne passe pas la clé : laissée intacte
    assert repair_ocr_ids("SIREN 4l8273646") == "SIREN 4l8273646"
