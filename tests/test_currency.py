import pytest

from iso8583_decoder.currency import (
    DEFAULT_TABLE_PATH,
    format_amount,
    load_currency_exponents,
)


@pytest.fixture
def exponents():
    return load_currency_exponents(DEFAULT_TABLE_PATH)


def test_table_loads_known_codes(exponents):
    assert exponents["840"] == 2   # USD
    assert exponents["392"] == 0   # JPY
    assert exponents["048"] == 3   # BHD


def test_two_exponent_currency_is_correct_not_just_non_crashing(exponents):
    # 4200 minor units of USD is $42.00, not $4200.00 or $420.0
    result = format_amount({4: "000000004200", 49: "840"}, exponents)
    assert result.formatted == "42.00"
    assert result.exponent_used == 2
    assert result.assumed is False
    assert result.diagnostics == []


def test_jpy_amount_has_zero_decimal_places(exponents):
    result = format_amount({4: "000000050000", 49: "392"}, exponents)
    assert result.formatted == "50000"
    assert result.exponent_used == 0
    assert result.assumed is False


def test_three_exponent_currency(exponents):
    # BHD: 1234 minor units is 1.234 BHD, not 12.34
    result = format_amount({4: "000000001234", 49: "048"}, exponents)
    assert result.formatted == "1.234"
    assert result.exponent_used == 3
    assert result.assumed is False


def test_missing_field_49_does_not_assume_exponent(exponents):
    result = format_amount({4: "000000004200"}, exponents)
    assert result.assumed is True
    assert result.exponent_used is None
    assert result.currency_code is None
    assert result.formatted == "4200"  # minor units, not a guessed "42.00"
    codes = [d.code for d in result.diagnostics]
    assert codes == ["amount_currency_missing"]


def test_unknown_field_49_code_does_not_assume_exponent(exponents):
    result = format_amount({4: "000000004200", 49: "999"}, exponents)
    assert result.assumed is True
    assert result.exponent_used is None
    assert result.currency_code == "999"  # preserved for troubleshooting, even though unresolved
    assert result.formatted == "4200"
    codes = [d.code for d in result.diagnostics]
    assert codes == ["amount_currency_unknown"]
