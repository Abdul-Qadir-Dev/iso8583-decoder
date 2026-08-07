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
    codes = [d.code for d in result.diagnostics]
    assert "field_data_type_mismatch" in codes


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
