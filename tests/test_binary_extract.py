from iso8583_decoder.binary_extract import extract_fields_binary
from tests.hex_helpers import ascii_hex, pack_bcd


def test_fixed_and_variable_numeric_fields(spec):
    # field 3 (fixed6, even) + field 32 (LLVAR, prefix "06" + 6-digit value)
    body = pack_bcd("000000") + pack_bcd("06") + pack_bcd("123456")
    result = extract_fields_binary(body, [3, 32], spec)
    assert result.decoded_so_far == {3: "000000", 32: "123456"}
    assert result.diagnostics == []
    assert result.stop is None


def test_odd_digit_field_unpacks_with_leading_pad(spec):
    # field 22, POS Entry Mode, fixed3 (odd digit count) -- default bcd_pad is leading
    assert spec.fields[22].bcd_pad.value == "leading"
    body = pack_bcd("051", pad_leading=True)
    result = extract_fields_binary(body, [22], spec)
    assert result.decoded_so_far == {22: "051"}
    assert result.diagnostics == []


def test_pack_bcd_test_helper_itself():
    # sanity check on the test helper before trusting it in other tests
    assert pack_bcd("051") == "f051"
    assert pack_bcd("000000") == "000000"  # even -- unchanged


def test_alphanumeric_field_decoded_from_ascii_bytes(spec):
    body = ascii_hex("TERM0001")  # field 41, ans, fixed8
    result = extract_fields_binary(body, [41], spec)
    assert result.decoded_so_far == {41: "TERM0001"}


def test_binary_field_is_not_doubled_like_ascii_mode(spec):
    # field 52, PIN Data, fixed length 8 (bytes) -- binary mode reads it directly
    # as 8 bytes = 16 hex chars, no *2 needed since declared_length is already bytes
    body = "0102030405060708"
    result = extract_fields_binary(body, [52], spec)
    assert result.decoded_so_far == {52: "0102030405060708"}


def test_invalid_bcd_nibble_in_data_is_diagnostic_not_stop(spec):
    # field 3 fixed6: byte 0xAB has nibble 'a' (10), not a valid digit
    body = "ab" + "0000"  # 6 nibbles total: a,b,0,0,0,0
    result = extract_fields_binary(body, [3], spec)
    assert result.stop is None
    assert result.decoded_so_far[3] == "ab0000"  # invalid nibbles preserved as hex chars
    codes = [d.code for d in result.diagnostics]
    assert codes.count("field_invalid_bcd_nibble") == 2  # both 'a' and 'b' are invalid
    for d in result.diagnostics:
        assert d.field_number == 3
        assert d.byte_offset == 0  # byte position where field 3's value begins


def test_invalid_bcd_nibble_in_length_prefix_stops(spec):
    # field 32's LLVAR prefix: byte 0xAB isn't valid BCD in either nibble
    body = "ab" + "123456"
    result = extract_fields_binary(body, [32], spec)
    assert result.stop is not None
    assert result.stop.stopped_at == "field_32"
    assert result.stop.reason.code == "field_length_prefix_invalid_bcd"
    assert result.decoded_so_far == {}


def test_length_exceeding_remaining_is_diagnostic_not_stop(spec):
    # field 3 is fixed6 (3 bytes BCD), only 1 byte remains
    body = "12"
    result = extract_fields_binary(body, [3], spec)
    assert result.stop is None
    codes = [d.code for d in result.diagnostics]
    assert "field_fixed_length_exceeds_remaining" in codes


def test_trailing_bytes_is_diagnostic(spec):
    body = pack_bcd("00") + "ff"  # field 25 (fixed2) + one unaccounted trailing byte
    result = extract_fields_binary(body, [25], spec)
    assert result.stop is None
    trailing = [d for d in result.diagnostics if d.code == "trailing_bytes"]
    assert len(trailing) == 1
    assert "1" in trailing[0].message


def test_field_not_in_spec_stops(spec):
    result = extract_fields_binary("ffff", [999], spec)
    assert result.stop is not None
    assert result.stop.reason.code == "field_spec_missing"
    assert result.decoded_so_far == {}


def test_interpretation_raw_field_decodes_and_raises_a_non_stop_diagnostic(spec):
    # field 62: ans, LLLVAR -- prefix "010" is odd-digit BCD (needs a pad nibble),
    # value stays plain ASCII bytes even in binary mode since it's an ans field
    body = pack_bcd("010") + ascii_hex("PROC-DATA1")
    result = extract_fields_binary(body, [62], spec)
    assert result.stop is None
    assert result.decoded_so_far == {62: "PROC-DATA1"}
    diag = next(d for d in result.diagnostics if d.code == "field_raw_not_interpreted")
    assert diag.field_number == 62
    assert "10 bytes" in diag.message
    assert diag.severity.value == "diagnostic"


def test_field_after_an_interpretation_raw_field_still_decodes_correctly(spec):
    body = pack_bcd("010") + ascii_hex("PROC-DATA1") + pack_bcd("301")  # field 62 then field 70
    result = extract_fields_binary(body, [62, 70], spec)
    assert result.stop is None
    assert result.decoded_so_far == {62: "PROC-DATA1", 70: "301"}
