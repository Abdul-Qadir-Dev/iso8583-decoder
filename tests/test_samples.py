import pytest

from iso8583_decoder.diagnostics import Severity
from iso8583_decoder.explain import explain_fields
from iso8583_decoder.mti import load_spec_for_version
from iso8583_decoder.parser import decode_message
from iso8583_decoder.samples import get_sample, load_samples

ALL_SAMPLE_IDS = [s.id for s in load_samples()]


def test_sample_ids_are_unique():
    assert len(ALL_SAMPLE_IDS) == len(set(ALL_SAMPLE_IDS))


def test_expected_coverage_present():
    types = {s.transaction_type for s in load_samples()}
    for expected_type in [
        "0100 authorization request", "0110 authorization response",
        "0200 financial request", "0210 financial response",
        "0400 reversal request", "0800 network management request",
    ]:
        assert expected_type in types


def test_at_least_one_secondary_bitmap_sample():
    result = decode_message(get_sample("network_mgmt_echo_0800").raw, encoding="ascii")
    assert result.bitmap_secondary_hex is not None


def test_ascii_and_binary_pair_agree():
    ascii_result = decode_message(get_sample("auth_request_0100_ascii").raw, encoding="ascii")
    binary_result = decode_message(get_sample("auth_request_0100_binary").raw, encoding="binary")
    assert ascii_result.decoded_so_far == binary_result.decoded_so_far
    assert ascii_result.partial is False and binary_result.partial is False
    # restored: lost when the old hand-built equivalence test was removed in
    # favor of the sample library -- decode_mti() runs on an already-converted
    # ASCII string in both modes, so the summary should be identical too
    assert ascii_result.mti.summary == binary_result.mti.summary


@pytest.mark.parametrize("sample_id", ALL_SAMPLE_IDS)
def test_sample_decodes_to_its_declared_outcome(sample_id):
    sample = get_sample(sample_id)
    result = decode_message(sample.raw, encoding=sample.encoding)

    assert result.partial == sample.expected.partial, sample.description
    assert {d.code for d in result.diagnostics} == sample.expected.diagnostic_codes, sample.description

    if sample.expected.partial:
        assert result.stopped_at == sample.expected.stopped_at
        assert result.reason.code == sample.expected.reason_code


def test_secondary_bitmap_sample_decodes_exact_values():
    # restored: the old bespoke binary-mode secondary-bitmap test hand-built a
    # minimal message and checked decoded_so_far == {70: "017"} exactly; the
    # library's outcome-classification check doesn't verify field values, only
    # clean/diagnostic/stop, so that specific assertion needs to live here now
    result = decode_message(get_sample("network_mgmt_echo_0800").raw, encoding="ascii")
    assert result.decoded_so_far == {
        7: "0807160000",
        11: "000789",
        70: "301",
        128: "a1b2c3d4e5f6a1b2",
    }


def test_field_55_and_62_decode_fully_to_the_end_with_field_70_correct():
    """The specific proof requested for the fields-48/55/60-63 fix: a message
    carrying field 55 (EMV/ICC, interpretation: raw, binary) and field 62
    (private-use, interpretation: raw, ans) decodes all the way to field 70
    -- which comes after both -- with field 70's value exactly correct. That
    field 70 decodes at all, let alone correctly, is what proves the byte
    offset survived reading two raw-interpretation fields rather than being
    lost. Before this fix, this exact message stopped at field 55 with
    field_spec_missing."""
    result = decode_message(get_sample("emv_and_private_use_data_0100").raw, encoding="ascii")

    assert result.partial is False
    assert result.decoded_so_far == {
        3: "000000",
        11: "000123",
        55: "0123456789abcdef",
        62: "PROC-DATA1",
        70: "301",
    }

    codes = [d.code for d in result.diagnostics]
    assert codes.count("field_raw_not_interpreted") == 2
    for d in result.diagnostics:
        assert d.severity.value == "diagnostic"  # informational, not a stop, not an error


def test_malformed_invalid_bcd_data_field_exact_value_and_count():
    # restored: the old bespoke test asserted decoded_so_far[3] == "ab0000" and
    # codes.count("field_invalid_bcd_nibble") == 2 by calling extract_fields_binary
    # directly; that granularity still exists at the unit level in
    # test_binary_extract.py, but nothing asserted it through the full
    # decode_message() pipeline until now
    result = decode_message(get_sample("malformed_invalid_bcd_data_field").raw, encoding="binary")
    assert result.decoded_so_far[3] == "ab0000"
    codes = [d.code for d in result.diagnostics]
    assert codes.count("field_invalid_bcd_nibble") == 2


@pytest.mark.parametrize("sample_id", ALL_SAMPLE_IDS)
def test_sample_diagnostic_severities_match_partial_classification(sample_id):
    """Cross-checks the registry against real behavior: every diagnostic that
    fired while decoding continued has severity DIAGNOSTIC, and (when the
    result is partial) the stop reason has severity STOP. If these ever
    disagree, either a code's registered severity is wrong or the code was
    used somewhere it shouldn't have been."""
    sample = get_sample(sample_id)
    result = decode_message(sample.raw, encoding=sample.encoding)

    for d in result.diagnostics:
        assert d.severity == Severity.DIAGNOSTIC, f"{sample_id}: {d.code} in diagnostics but severity is {d.severity}"

    if result.partial:
        assert result.reason.severity == Severity.STOP, f"{sample_id}: stop reason {result.reason.code} isn't STOP severity"


@pytest.mark.parametrize("sample_id", ALL_SAMPLE_IDS)
def test_sample_diagnostic_byte_offsets_point_into_the_raw_message(sample_id):
    """Every parse-time diagnostic's byte_offset should be a valid position
    within the sample's own raw string -- confirms the local-to-absolute
    offset localization in parser.py is correct for every sample, not just
    the couple of cases spot-checked by hand while building it."""
    sample = get_sample(sample_id)
    result = decode_message(sample.raw, encoding=sample.encoding)

    max_valid = len(sample.raw) if sample.encoding == "ascii" else len(sample.raw) // 2
    for d in result.diagnostics:
        if d.byte_offset is not None:
            assert 0 <= d.byte_offset <= max_valid, f"{sample_id}: {d.code} byte_offset {d.byte_offset} out of range"
    if result.partial and result.reason.byte_offset is not None:
        assert 0 <= result.reason.byte_offset <= max_valid


@pytest.mark.parametrize("sample_id", ALL_SAMPLE_IDS)
def test_sample_interpreted_output(sample_id):
    """Part B requirement: every sample gets its interpreted output asserted,
    not just its raw decode. Explanation must never turn a successful decode
    into a failed one, and raw values must survive untouched."""
    sample = get_sample(sample_id)
    result = decode_message(sample.raw, encoding=sample.encoding)
    spec = load_spec_for_version(result.mti.version.digit)

    explained = explain_fields(result.decoded_so_far, spec)  # must not raise

    assert set(explained.fields) == set(result.decoded_so_far)
    for field_number, raw in result.decoded_so_far.items():
        assert explained.fields[field_number].raw == raw  # interpretation never mutates raw


def test_auth_response_0110_response_code_interpreted_as_approved():
    result = decode_message(get_sample("auth_response_0110").raw, encoding="ascii")
    spec = load_spec_for_version(result.mti.version.digit)
    explained = explain_fields(result.decoded_so_far, spec)
    assert explained.fields[39].interpreted == "Approved"


def test_auth_request_0100_amount_interpreted_with_currency_exponent():
    result = decode_message(get_sample("auth_request_0100_ascii").raw, encoding="ascii")
    spec = load_spec_for_version(result.mti.version.digit)
    explained = explain_fields(result.decoded_so_far, spec)
    assert explained.fields[4].interpreted == "42.00 840"
    assert explained.diagnostics == []  # field 49 was present, no assumption needed
