import pytest

from iso8583_decoder.mti import MtiFormatError, UnsupportedVersionError
from iso8583_decoder.parser import decode_message
from iso8583_decoder.samples import get_sample
from tests.hex_helpers import bitmap_hex

PAN = "4111111111111111"  # standard test PAN, not shaped like real client data


def test_complete_realistic_auth_request_decoded_field_by_field():
    # Sourced from the sample library (auth_request_0100_ascii) rather than
    # hand-built here, so this and the library agree on what "the" realistic
    # auth request looks like. Kept as its own test, distinct from the
    # library's generic outcome-classification check, because it verifies
    # exact field values -- the parametrized check in test_samples.py only
    # verifies clean/diagnostic/stop classification, not the values.
    sample = get_sample("auth_request_0100_ascii")
    result = decode_message(sample.raw, encoding=sample.encoding)

    assert result.partial is False
    assert result.diagnostics == []
    assert result.mti.summary == "Authorization request from acquirer"
    assert result.decoded_so_far == {
        2: PAN,
        3: "000000",
        4: "000000004200",
        7: "0807143000",
        11: "000123",
        12: "143000",
        13: "0807",
        22: "051",
        25: "00",
        32: "123456",
        37: "123456789012",
        41: "TERM0001",
        42: "MERCHANT0000001",
        49: "840",
    }


def test_continue_anyway_diagnostics_then_a_stop_condition_in_one_message():
    # field 3: present but its value doesn't match numeric -- diagnostic, continues.
    # field 60: bit set but not in the spec -- diagnostic at the bitmap stage,
    #           then a stop once extraction actually reaches it.
    # field 70: legitimately defined and bit-set (in the secondary bitmap),
    #           but never reached because the stop at field 60 halts
    #           extraction before getting there.
    primary = bitmap_hex({1, 3, 32, 39, 60}, base_field=1)  # bit 1 -> secondary bitmap follows
    secondary = bitmap_hex({70}, base_field=65)
    body = "ABCDEF" + "05" + "12345" + "00" + "TAIL-NEVER-READ"
    raw = "0100" + primary + secondary + body

    result = decode_message(raw, encoding="ascii")

    assert result.partial is True
    assert result.stopped_at == "field_60"
    assert result.reason.code == "field_spec_missing"

    codes = [d.code for d in result.diagnostics]
    assert "bitmap_field_not_in_spec" in codes    # field 60's bit, flagged at the bitmap stage
    assert "field_data_type_mismatch" in codes    # field 3's non-numeric value

    assert result.decoded_so_far == {3: "ABCDEF", 32: "12345", 39: "00"}
    assert 60 not in result.decoded_so_far
    assert 70 not in result.decoded_so_far  # never reached, extraction stopped first


def test_bitmap_level_stop_produces_no_decoded_fields():
    # bit 1 set, but nothing follows the primary bitmap at all.
    primary = bitmap_hex({1, 2}, base_field=1)
    raw = "0100" + primary

    result = decode_message(raw, encoding="ascii")

    assert result.partial is True
    assert result.stopped_at == "secondary_bitmap"
    assert result.reason.code == "bitmap_secondary_missing"
    assert result.decoded_so_far == {}


def test_malformed_mti_raises():
    with pytest.raises(MtiFormatError):
        decode_message("01", encoding="ascii")


def test_unsupported_mti_version_raises():
    primary = bitmap_hex({2}, base_field=1)
    raw = "1100" + primary + "0" * 20  # version digit '1' -> 1993, no spec mapped yet
    with pytest.raises(UnsupportedVersionError):
        decode_message(raw, encoding="ascii")


# Binary-mode equivalence, the secondary-bitmap path, and the two BCD
# anomaly cases (invalid nibble in data vs. in a length prefix) are now
# covered by the sample library instead of hand-built here -- see
# tests/test_samples.py, which decodes every sample and checks it against
# its declared expected outcome, plus a dedicated ascii/binary agreement
# check on the auth_request_0100 pair.
