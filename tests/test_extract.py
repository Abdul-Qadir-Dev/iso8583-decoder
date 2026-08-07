from iso8583_decoder.extract import extract_fields


def test_fixed_and_variable_fields_extracted_correctly(spec):
    body = "000000" + "05" + "12345"  # field 3 (fixed6), field 32 (LLVAR)
    result = extract_fields(body, [3, 32], spec)
    assert result.decoded_so_far == {3: "000000", 32: "12345"}
    assert result.diagnostics == []
    assert result.stop is None


def test_binary_field_consumes_two_hex_chars_per_byte(spec):
    body = "0102030405060708"  # field 52, PIN Data, 8 bytes -> 16 hex chars
    result = extract_fields(body, [52], spec)
    assert result.decoded_so_far == {52: "0102030405060708"}
    assert result.diagnostics == []


def test_variable_length_exceeding_remaining_is_diagnostic_not_stop(spec):
    body = "20" + "ABCDE"  # field 32 prefix claims 20 chars, only 5 remain
    result = extract_fields(body, [32], spec)
    assert result.stop is None
    assert result.decoded_so_far[32] == "ABCDE"  # truncated to what's actually there
    codes = [d.code for d in result.diagnostics]
    assert "field_variable_length_exceeds_remaining" in codes


def test_fixed_length_exceeding_remaining_is_diagnostic_not_stop(spec):
    body = "12"  # field 3 is fixed6, only 2 chars remain
    result = extract_fields(body, [3], spec)
    assert result.stop is None
    assert result.decoded_so_far[3] == "12"
    codes = [d.code for d in result.diagnostics]
    assert "field_fixed_length_exceeds_remaining" in codes


def test_data_type_mismatch_is_diagnostic_not_stop(spec):
    body = "ABCDEF"  # field 3 is numeric, this isn't
    result = extract_fields(body, [3], spec)
    assert result.stop is None
    assert result.decoded_so_far[3] == "ABCDEF"
    mismatch = next(d for d in result.diagnostics if d.code == "field_data_type_mismatch")
    assert mismatch.field_number == 3
    assert mismatch.byte_offset == 0  # field 3 starts at the beginning of this body


def test_trailing_bytes_after_last_field_is_diagnostic(spec):
    body = "00" + "EXTRA"  # field 39 (fixed2) consumes "00", "EXTRA" is unaccounted for
    result = extract_fields(body, [39], spec)
    assert result.stop is None
    assert result.decoded_so_far[39] == "00"
    trailing = [d for d in result.diagnostics if d.code == "trailing_bytes"]
    assert len(trailing) == 1
    assert "5" in trailing[0].message


def test_unreadable_length_prefix_stops(spec):
    body = "AB12345"  # field 32's 2-digit prefix isn't numeric
    result = extract_fields(body, [32], spec)
    assert result.stop is not None
    assert result.stop.stopped_at == "field_32"
    assert result.stop.reason.code == "field_length_prefix_unreadable"
    assert result.decoded_so_far == {}


def test_truncated_length_prefix_stops(spec):
    body = "0"  # field 32 needs a 2-digit prefix, only 1 char left
    result = extract_fields(body, [32], spec)
    assert result.stop is not None
    assert result.stop.reason.code == "field_length_prefix_truncated"


def test_field_not_in_spec_stops(spec):
    result = extract_fields("whatever", [999], spec)
    assert result.stop is not None
    assert result.stop.stopped_at == "field_999"
    assert result.stop.reason.code == "field_spec_missing"
    assert result.decoded_so_far == {}


def test_stop_preserves_fields_decoded_before_it(spec):
    body = "000000" + "whatever-for-999"
    result = extract_fields(body, [3, 999], spec)
    assert result.decoded_so_far == {3: "000000"}
    assert result.stop.stopped_at == "field_999"
    assert result.stop.reason.byte_offset == 6  # right after field 3's 6 characters


def test_interpretation_raw_field_decodes_and_raises_a_non_stop_diagnostic(spec):
    # field 62: ans, LLLVAR, interpretation: raw
    body = "010" + "PROC-DATA1"  # 3-digit length prefix + 10 chars
    result = extract_fields(body, [62], spec)
    assert result.stop is None
    assert result.decoded_so_far == {62: "PROC-DATA1"}
    diag = next(d for d in result.diagnostics if d.code == "field_raw_not_interpreted")
    assert diag.field_number == 62
    assert "10 characters" in diag.message
    assert diag.severity.value == "diagnostic"  # not a stop


def test_interpretation_raw_binary_field_reports_byte_count_not_char_count(spec):
    # field 55: b, LLLVAR, interpretation: raw -- ASCII mode, hex text, 2 chars/byte
    value = "0123456789abcdef"  # 16 hex chars = 8 bytes
    body = "008" + value
    result = extract_fields(body, [55], spec)
    assert result.decoded_so_far == {55: value}
    diag = next(d for d in result.diagnostics if d.code == "field_raw_not_interpreted")
    assert "8 bytes" in diag.message


def test_field_after_an_interpretation_raw_field_still_decodes_correctly(spec):
    # proves the byte offset survived past a raw field, not just that the
    # raw field itself decoded
    body = "010" + "PROC-DATA1" + "301"  # field 62 (LLLVAR) then field 70 (fixed3)
    result = extract_fields(body, [62, 70], spec)
    assert result.stop is None
    assert result.decoded_so_far == {62: "PROC-DATA1", 70: "301"}
