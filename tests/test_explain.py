from iso8583_decoder.diagnostics import DiagnosticCode
from iso8583_decoder.explain import explain_fields
from iso8583_decoder.mti import load_spec_for_version


def spec1987():
    return load_spec_for_version("0")


def test_processing_code_splits_into_three_parts():
    explained = explain_fields({3: "000000"}, spec1987())
    interpreted = explained.fields[3].interpreted
    assert "Purchase" in interpreted
    assert "from account" in interpreted
    assert "to account" in interpreted


def test_processing_code_unmapped_subpart_is_labeled_not_errored():
    explained = explain_fields({3: "999999"}, spec1987())
    interpreted = explained.fields[3].interpreted
    assert "unmapped" in interpreted
    assert explained.diagnostics == []


def test_amount_uses_currency_exponent_not_hardcoded_divide_by_100():
    # BHD exponent is 3, not 2 -- 1234 minor units is 1.234, not 12.34
    explained = explain_fields({4: "000000001234", 49: "048"}, spec1987())
    assert explained.fields[4].interpreted == "1.234 048"


def test_amount_missing_field_49_does_not_silently_divide_by_100():
    explained = explain_fields({4: "000000004200"}, spec1987())
    interpreted = explained.fields[4].interpreted
    assert "42.00" not in interpreted
    assert "4200" in interpreted
    codes = [d.code for d in explained.diagnostics]
    assert DiagnosticCode.AMOUNT_CURRENCY_MISSING in codes


def test_amount_unknown_currency_code_does_not_assume_exponent():
    explained = explain_fields({4: "000000004200", 49: "999"}, spec1987())
    interpreted = explained.fields[4].interpreted
    assert "42.00" not in interpreted
    assert "4200" in interpreted
    codes = [d.code for d in explained.diagnostics]
    assert DiagnosticCode.AMOUNT_CURRENCY_UNKNOWN in codes


def test_currency_field_itself_reports_exponent():
    explained = explain_fields({49: "392"}, spec1987())  # JPY, exponent 0
    assert explained.fields[49].interpreted == "minor-unit exponent 0"


def test_currency_field_unmapped_code_degrades_gracefully():
    explained = explain_fields({49: "999"}, spec1987())
    assert "unmapped" in explained.fields[49].interpreted
    assert explained.diagnostics == []


def test_response_code_known_value():
    explained = explain_fields({39: "00"}, spec1987())
    assert explained.fields[39].interpreted == "Approved"


def test_response_code_unmapped_value_degrades_gracefully_not_an_error():
    explained = explain_fields({39: "77"}, spec1987())
    assert explained.fields[39].interpreted == "unmapped code: '77'"
    assert explained.diagnostics == []  # unmapped is not a diagnostic


def test_pos_entry_mode_and_condition_code_value_maps():
    explained = explain_fields({22: "051", 25: "00"}, spec1987())
    assert "chip" in explained.fields[22].interpreted.lower()
    assert explained.fields[25].interpreted == "Normal presentment"


def test_date_mmdd_marks_year_absent_not_fabricated():
    explained = explain_fields({13: "0807"}, spec1987())
    interpreted = explained.fields[13].interpreted
    assert "08-07" in interpreted
    assert "year not present" in interpreted
    # no 4-digit year anywhere in the output
    import re
    assert not re.search(r"\b(19|20)\d{2}\b", interpreted)


def test_time_hhmmss_formats_without_claiming_a_date():
    explained = explain_fields({12: "143000"}, spec1987())
    assert explained.fields[12].interpreted == "14:30:00"


def test_datetime_mmddhhmmss_marks_year_absent():
    explained = explain_fields({7: "0807143000"}, spec1987())
    interpreted = explained.fields[7].interpreted
    assert interpreted == "08-07 14:30:00 (year not present in message)"


def test_expiry_yymm_does_carry_a_year_since_it_is_actually_present():
    # unlike 7/12/13, field 14's YY really is in the data -- prefixing "20"
    # is a display convention on real data, not fabrication
    explained = explain_fields({14: "2512"}, spec1987())
    assert explained.fields[14].interpreted == "2025-12"


def test_fields_without_a_value_map_or_format_hint_are_not_interpreted():
    # PAN, RRN, terminal ID etc. are identifiers, not codes -- nothing to interpret
    explained = explain_fields({2: "4111111111111111", 41: "TERM0001"}, spec1987())
    assert explained.fields[2].interpreted is None
    assert explained.fields[41].interpreted is None


def test_raw_values_survive_interpretation_unchanged():
    decoded = {3: "000000", 4: "000000004200", 49: "840", 39: "00", 2: "4111111111111111"}
    explained = explain_fields(decoded, spec1987())
    for field_number, raw in decoded.items():
        assert explained.fields[field_number].raw == raw


def test_unknown_field_number_not_in_spec_does_not_crash():
    # shouldn't normally happen (decoded_so_far only has fields the spec
    # defines) but explanation must never turn a successful decode into a
    # failed one, so this must degrade rather than raise
    explained = explain_fields({999: "whatever"}, spec1987())
    assert explained.fields[999].interpreted is None
    assert explained.fields[999].raw == "whatever"
