from datetime import date
from decimal import Decimal

import pytest

from facturia.normalize import find_dates, fmt_amount, parse_amount, parse_rate


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1 234,56 €", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1234.56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("12 000", "12000"),
        ("49,9", "49.9"),
        ("1.234", "1234"),
        ("2 880,00 EUR", "2880.00"),
    ],
)
def test_parse_amount_french_formats(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


def test_find_dates_all_formats_in_order():
    text = "Émise le 5 septembre 2026, échéance 2026-10-20 ou 20/10/2026, sinon 1er oct. 2026"
    assert find_dates(text) == [
        date(2026, 9, 5),
        date(2026, 10, 20),
        date(2026, 10, 20),
        date(2026, 10, 1),
    ]


def test_invalid_dates_are_ignored():
    assert find_dates("31/02/2026") == []


def test_rate_and_format():
    assert parse_rate("TVA 5,5 %") == Decimal("5.5")
    assert fmt_amount(Decimal("1234567.8")) == "1 234 567,80"
