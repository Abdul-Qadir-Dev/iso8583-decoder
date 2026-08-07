import pytest

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


@pytest.mark.parametrize("sample_id", ALL_SAMPLE_IDS)
def test_sample_decodes_to_its_declared_outcome(sample_id):
    sample = get_sample(sample_id)
    result = decode_message(sample.raw, encoding=sample.encoding)

    assert result.partial == sample.expected.partial, sample.description
    assert {d.code for d in result.diagnostics} == sample.expected.diagnostic_codes, sample.description

    if sample.expected.partial:
        assert result.stopped_at == sample.expected.stopped_at
        assert result.reason.code == sample.expected.reason_code
