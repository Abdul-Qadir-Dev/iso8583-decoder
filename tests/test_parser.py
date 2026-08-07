import pytest

from iso8583_decoder.mti import MtiFormatError, UnsupportedVersionError
from iso8583_decoder.parser import decode_message
from tests.hex_helpers import ascii_hex, bitmap_hex, pack_bcd

PAN = "4111111111111111"  # standard test PAN, not shaped like real client data


def test_complete_realistic_auth_request_decoded_field_by_field():
    fields = {
        2: "16" + PAN,            # PAN, LLVAR
        3: "000000",              # processing code
        4: "000000004200",        # amount, minor units
        11: "000123",             # STAN
        12: "143000",             # local time
        13: "0807",               # local date
        22: "051",                # POS entry mode
        25: "00",                 # POS condition code
        32: "06" + "123456",      # acquiring institution ID, LLVAR
        37: "123456789012",       # retrieval reference number
        41: "TERM0001",           # terminal ID
        42: "MERCHANT0000001",    # card acceptor ID
        49: "840",                # currency: USD
    }
    body = "".join(fields[n] for n in sorted(fields))
    primary = bitmap_hex(set(fields), base_field=1)
    raw = "0100" + primary + body

    result = decode_message(raw, encoding="ascii")

    assert result.partial is False
    assert result.diagnostics == []
    assert result.mti.summary == "Authorization request from acquirer"
    assert result.decoded_so_far == {
        2: PAN,
        3: "000000",
        4: "000000004200",
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


# --- binary mode -----------------------------------------------------------

def _build_ascii_message(fields: dict[int, str]) -> str:
    body = "".join(fields[n] for n in sorted(fields))
    primary = bitmap_hex(set(fields), base_field=1)
    return "0100" + primary + body


def _build_binary_message(fields_ascii: dict[int, str], numeric_fields: set[int]) -> str:
    """fields_ascii holds each field's value the same way the ASCII test writes
    it (digits as digit characters, LLVAR fields pre-fixed with their 2-digit
    length). numeric_fields says which ones get BCD-packed; everything else is
    packed as raw ASCII bytes -- mirroring how a real message would carry the
    same information in each mode, not just re-encoding the same text."""
    parts = []
    for n in sorted(fields_ascii):
        value = fields_ascii[n]
        if n in numeric_fields:
            if n in (2, 32):  # LLVAR: first 2 chars are the length prefix, BCD too
                parts.append(pack_bcd(value[:2]) + pack_bcd(value[2:]))
            else:
                parts.append(pack_bcd(value))
        else:
            parts.append(ascii_hex(value))
    body = "".join(parts)
    primary = bitmap_hex(set(fields_ascii), base_field=1)
    return ascii_hex("0100") + primary + body


def test_binary_mode_agrees_with_ascii_mode_on_the_same_message():
    fields_ascii = {
        2: "16" + PAN,
        3: "000000",
        4: "000000004200",
        11: "000123",
        12: "143000",
        13: "0807",
        22: "051",              # odd digit count -- exercises BCD padding
        25: "00",
        32: "06" + "123456",
        37: "123456789012",     # an -- stays ASCII bytes, not BCD
        41: "TERM0001",         # ans
        42: "MERCHANT0000001",  # ans
        49: "840",              # odd digit count -- exercises BCD padding
    }
    numeric_fields = {2, 3, 4, 11, 12, 13, 22, 25, 32, 49}

    ascii_raw = _build_ascii_message(fields_ascii)
    binary_raw = _build_binary_message(fields_ascii, numeric_fields)

    ascii_result = decode_message(ascii_raw, encoding="ascii")
    binary_result = decode_message(binary_raw, encoding="binary")

    assert ascii_result.partial is False
    assert binary_result.partial is False
    assert ascii_result.diagnostics == []
    assert binary_result.diagnostics == []

    # the actual point of this test: both modes agree on every field, not just
    # that each one runs without crashing
    assert binary_result.decoded_so_far == ascii_result.decoded_so_far
    assert binary_result.decoded_so_far == {
        2: PAN,
        3: "000000",
        4: "000000004200",
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
    assert binary_result.mti.summary == ascii_result.mti.summary


def test_binary_mode_packed_bitmap_with_secondary_present():
    # field 70 is 65-128: needs bit 1 set in the primary bitmap plus a real
    # secondary bitmap block. The bitmap parser is shared with ASCII mode, so
    # this is really confirming the binary decode path feeds it correctly.
    primary = bitmap_hex({1}, base_field=1)   # bit 1 -> secondary bitmap follows
    secondary = bitmap_hex({70}, base_field=65)
    body = pack_bcd("017")  # field 70, Network Management Information Code, fixed3 (odd)
    raw = ascii_hex("0800") + primary + secondary + body

    result = decode_message(raw, encoding="binary")

    assert result.partial is False
    assert result.decoded_so_far == {70: "017"}


def test_binary_mode_invalid_bcd_nibble_in_data_field_is_diagnostic():
    primary = bitmap_hex({3}, base_field=1)
    body = "ab0000"  # field 3, fixed6: nibbles a,b are invalid BCD
    raw = ascii_hex("0100") + primary + body

    result = decode_message(raw, encoding="binary")

    assert result.partial is False
    assert result.decoded_so_far[3] == "ab0000"
    codes = [d.code for d in result.diagnostics]
    assert codes.count("field_invalid_bcd_nibble") == 2


def test_binary_mode_invalid_bcd_nibble_in_length_prefix_stops():
    primary = bitmap_hex({32}, base_field=1)
    body = "ab" + "123456"  # field 32's LLVAR prefix isn't valid BCD
    raw = ascii_hex("0100") + primary + body

    result = decode_message(raw, encoding="binary")

    assert result.partial is True
    assert result.stopped_at == "field_32"
    assert result.reason.code == "field_length_prefix_invalid_bcd"
