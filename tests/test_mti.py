import pytest

from iso8583_decoder.mti import (
    CLASS_MEANINGS,
    FUNCTION_MEANINGS,
    ORIGIN_MEANINGS,
    VERSION_MEANINGS,
    MtiFormatError,
    UnsupportedVersionError,
    decode_mti,
    load_spec_for_version,
)


def test_reserved_digit_diagnostics_carry_byte_offset_and_no_field_number():
    # MTI isn't a numbered field, so field_number is None; byte_offset is the
    # digit's own position (0-3), always known since MTI is always 4 bytes first
    result = decode_mti("0090")  # class digit '0' at index 1, function '9' at index 2
    by_code = {d.code: d for d in result.diagnostics}
    assert by_code["mti_unknown_class"].field_number is None
    assert by_code["mti_unknown_class"].byte_offset == 1
    assert by_code["mti_unknown_function"].byte_offset == 2


def test_0100_reads_as_authorization_request_from_acquirer():
    result = decode_mti("0100")
    assert result.summary == "Authorization request from acquirer"
    assert result.diagnostics == []


@pytest.mark.parametrize("digit,expected", VERSION_MEANINGS.items())
def test_every_valid_version_digit(digit, expected):
    result = decode_mti(f"{digit}100")
    assert result.version.meaning == expected
    assert not any(d.code == "mti_unknown_version" for d in result.diagnostics)


@pytest.mark.parametrize("digit,expected", CLASS_MEANINGS.items())
def test_every_valid_class_digit(digit, expected):
    result = decode_mti(f"0{digit}00")
    assert result.message_class.meaning == expected
    assert not any(d.code == "mti_unknown_class" for d in result.diagnostics)


@pytest.mark.parametrize("digit,expected", FUNCTION_MEANINGS.items())
def test_every_valid_function_digit(digit, expected):
    result = decode_mti(f"01{digit}0")
    assert result.function.meaning == expected
    assert not any(d.code == "mti_unknown_function" for d in result.diagnostics)


@pytest.mark.parametrize("digit,expected", ORIGIN_MEANINGS.items())
def test_every_valid_origin_digit(digit, expected):
    result = decode_mti(f"010{digit}")
    assert result.origin.meaning == expected
    assert not any(d.code == "mti_unknown_origin" for d in result.diagnostics)


def test_reserved_version_digit_is_diagnostic_not_exception():
    result = decode_mti("5100")
    assert result.version.meaning is None
    assert result.version.digit == "5"
    codes = [d.code for d in result.diagnostics]
    assert "mti_unknown_version" in codes


def test_reserved_class_digit_is_diagnostic_not_exception():
    result = decode_mti("0000")
    assert result.message_class.meaning is None
    codes = [d.code for d in result.diagnostics]
    assert "mti_unknown_class" in codes
    # decoding continues -- origin/function still resolve normally
    assert result.function.meaning == "Request"
    assert result.origin.meaning == "Acquirer"


def test_reserved_function_digit_is_diagnostic_not_exception():
    result = decode_mti("0159")
    assert result.function.meaning is None
    assert any(d.code == "mti_unknown_function" for d in result.diagnostics)


def test_reserved_origin_digit_is_diagnostic_not_exception():
    result = decode_mti("0105")
    # digit 3 is 5 -- origin position, not class or function
    assert result.origin.meaning is None
    assert any(d.code == "mti_unknown_origin" for d in result.diagnostics)


def test_multiple_reserved_digits_all_reported():
    result = decode_mti("0090")
    codes = {d.code for d in result.diagnostics}
    assert codes == {"mti_unknown_class", "mti_unknown_function"}


def test_summary_uses_unknown_placeholder_for_reserved_digits():
    result = decode_mti("0090")
    assert "unknown class (0)" in result.summary
    assert "unknown function (9)" in result.summary


def test_non_numeric_mti_raises():
    with pytest.raises(MtiFormatError):
        decode_mti("01A0")


def test_truncated_mti_raises():
    with pytest.raises(MtiFormatError):
        decode_mti("010")


def test_empty_mti_raises():
    with pytest.raises(MtiFormatError):
        decode_mti("")


def test_load_spec_for_supported_version():
    spec = load_spec_for_version("0")
    assert spec.variant == "1987"
    assert 39 in spec.fields


def test_load_spec_for_unsupported_version_raises_clear_error_not_keyerror():
    with pytest.raises(UnsupportedVersionError):
        load_spec_for_version("1")
