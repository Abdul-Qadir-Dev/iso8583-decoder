import logging

import pytest
import yaml
from fastapi.testclient import TestClient

from iso8583_decoder.api import MAX_BODY_BYTES, create_app
from iso8583_decoder.diagnostics import DiagnosticCode
from iso8583_decoder.samples import DEFAULT_SAMPLES_PATH, load_samples

PAN = "4111111111111111"


@pytest.fixture
def client():
    # create_app() fresh per test -> a clean instance, no shared state across tests
    return TestClient(create_app(), raise_server_exceptions=False)


ALL_SAMPLE_IDS = [s.id for s in load_samples()]


# --- core principle: decode failures are 200s, not HTTP errors -------------

@pytest.mark.parametrize("sample_id", ALL_SAMPLE_IDS)
def test_every_sample_round_trips_and_matches_declared_outcome(client, sample_id):
    samples_by_id = {s.id: s for s in load_samples()}
    sample = samples_by_id[sample_id]

    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding})

    assert response.status_code == 200, f"{sample_id}: decode failure must still be a 200"
    body = response.json()
    assert body["partial"] == sample.expected.partial, sample_id

    # the API's diagnostics array additionally includes the stop reason (if
    # any), unlike the internal DecodeResult.diagnostics which keeps it
    # separate -- see api.py's _decode() for why
    expected_codes = set(sample.expected.diagnostic_codes)
    if sample.expected.partial:
        expected_codes.add(sample.expected.reason_code)
    assert {d["code"] for d in body["diagnostics"]} == expected_codes, sample_id

    if sample.expected.partial:
        assert body["stopped_at"] == sample.expected.stopped_at
        assert body["reason_code"] == sample.expected.reason_code


def test_stop_sample_returns_200_explicitly(client):
    # explicit per the spec: a stop must never surface as an HTTP error
    sample = next(s for s in load_samples() if s.id == "malformed_invalid_bcd_length_prefix")
    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding})
    assert response.status_code == 200
    body = response.json()
    assert body["partial"] is True
    assert body["reason_code"] == "field_length_prefix_invalid_bcd"


def test_unparseable_mti_still_returns_200_not_an_http_error(client):
    # decode_message() raises MtiFormatError for this input; the API must
    # catch it and report it the same way as any other stop
    response = client.post("/decode", json={"raw": "01", "encoding": "ascii"})
    assert response.status_code == 200
    body = response.json()
    assert body["mti"] is None
    assert body["partial"] is True
    assert body["stopped_at"] == "mti"
    assert body["reason_code"] == "mti_format_invalid"


def test_unsupported_mti_version_also_returns_200(client):
    from tests.hex_helpers import bitmap_hex

    raw = "1100" + bitmap_hex({2}, base_field=1) + "0" * 20  # version '1' -> 1993, unmapped
    response = client.post("/decode", json={"raw": raw, "encoding": "ascii"})
    assert response.status_code == 200
    body = response.json()
    assert body["reason_code"] == "mti_version_unsupported"


# --- explain -----------------------------------------------------------

def test_explain_false_omits_interpretation(client):
    sample = next(s for s in load_samples() if s.id == "auth_response_0110")
    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding, "explain": False})
    body = response.json()
    field_39 = next(f for f in body["fields"] if f["field_number"] == 39)
    assert field_39["interpreted"] is None


def test_explain_true_adds_interpretation(client):
    sample = next(s for s in load_samples() if s.id == "auth_response_0110")
    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding, "explain": True})
    body = response.json()
    field_39 = next(f for f in body["fields"] if f["field_number"] == 39)
    assert field_39["interpreted"] == "Approved"


def test_raw_values_are_byte_identical_between_explain_false_and_true(client):
    sample = next(s for s in load_samples() if s.id == "auth_request_0100_ascii")
    r_false = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding, "explain": False})
    r_true = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding, "explain": True})

    raw_false = {f["field_number"]: f["raw"] for f in r_false.json()["fields"]}
    raw_true = {f["field_number"]: f["raw"] for f in r_true.json()["fields"]}
    assert raw_false == raw_true


# --- reveal / masking -----------------------------------------------------

def test_pan_masked_by_default(client):
    sample = next(s for s in load_samples() if s.id == "auth_request_0100_ascii")
    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding})
    body = response.json()
    field_2 = next(f for f in body["fields"] if f["field_number"] == 2)
    assert field_2["raw"] != PAN
    assert PAN not in response.text


def test_reveal_true_shows_true_pan(client):
    sample = next(s for s in load_samples() if s.id == "auth_request_0100_ascii")
    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding, "reveal": True})
    body = response.json()
    field_2 = next(f for f in body["fields"] if f["field_number"] == 2)
    assert field_2["raw"] == PAN


# --- request validation -----------------------------------------------------

def test_missing_encoding_is_422(client):
    response = client.post("/decode", json={"raw": "0100"})
    assert response.status_code == 422


def test_invalid_encoding_value_is_422(client):
    response = client.post("/decode", json={"raw": "0100", "encoding": "ebcdic"})
    assert response.status_code == 422


def test_oversized_body_is_413(client):
    huge_raw = "A" * (MAX_BODY_BYTES + 1000)
    response = client.post("/decode", json={"raw": huge_raw, "encoding": "ascii"})
    assert response.status_code == 413


# --- security ---------------------------------------------------------------

def test_no_response_body_contains_the_input_pan_across_all_samples(client):
    for sample in load_samples():
        response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding})
        assert PAN not in response.text, f"{sample.id}: PAN leaked into response body"


def test_a_diagnostic_firing_on_the_pan_field_itself_does_not_leak_it(client):
    """The general PAN-leak checks above exercise samples where the malformed
    field isn't the sensitive one. This constructs a message where field 2
    (the PAN, masked-sensitivity) itself has an invalid BCD nibble, so the
    diagnostic pipeline (binary_extract.py, not just render.py in isolation)
    is what's actually under test here -- confirming no diagnostic message
    built from a corrupted PAN value reconstructs enough of it to matter."""
    from tests.hex_helpers import ascii_hex, bitmap_hex, pack_bcd

    corrupted = pack_bcd(PAN)
    corrupted = corrupted[:4] + "a" + corrupted[5:]  # one invalid nibble mid-PAN
    body = pack_bcd("16") + corrupted
    raw = ascii_hex("0100") + bitmap_hex({2}, base_field=1) + body

    response = client.post("/decode", json={"raw": raw, "encoding": "binary"})
    assert response.status_code == 200
    body_json = response.json()

    diag = next(d for d in body_json["diagnostics"] if d["code"] == "field_invalid_bcd_nibble")
    assert diag["field_number"] == 2
    # the diagnostic message names the single bad nibble, not the surrounding digits
    assert PAN not in diag["message"]
    assert PAN[:6] not in diag["message"] and PAN[-4:] not in diag["message"]

    # the corrupted field value in the response is masked by default too
    field_2 = next(f for f in body_json["fields"] if f["field_number"] == 2)
    assert PAN not in field_2["raw"]


def test_no_log_line_contains_the_input_pan(client, caplog):
    sample = next(s for s in load_samples() if s.id == "auth_request_0100_ascii")
    with caplog.at_level(logging.DEBUG):
        client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding, "reveal": True})
    for record in caplog.records:
        assert PAN not in record.getMessage()
        assert sample.raw not in record.getMessage()


def test_unhandled_exception_returns_generic_500_without_leaking_input(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(f"internal failure touching {PAN}")

    monkeypatch.setattr("iso8583_decoder.api.decode_message", boom)
    response = client.post("/decode", json={"raw": "0100", "encoding": "ascii"})
    assert response.status_code == 500
    assert PAN not in response.text
    assert response.json() == {"detail": "internal server error"}


def test_unhandled_exception_log_does_not_leak_input(client, caplog, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(f"internal failure touching {PAN}")

    monkeypatch.setattr("iso8583_decoder.api.decode_message", boom)
    with caplog.at_level(logging.DEBUG):
        client.post("/decode", json={"raw": "0100", "encoding": "ascii"})
    for record in caplog.records:
        assert PAN not in record.getMessage()


def test_404_and_422_paths_still_work_alongside_the_generic_handler(client):
    assert client.get("/samples/does-not-exist").status_code == 404
    assert client.post("/decode", json={"raw": "0100"}).status_code == 422


# --- diagnostics registry endpoint ------------------------------------------

def test_diagnostics_endpoint_returns_the_full_registry(client):
    response = client.get("/diagnostics")
    assert response.status_code == 200
    body = response.json()
    codes = {d["code"] for d in body}
    assert codes == {c.value for c in DiagnosticCode.all()}
    for entry in body:
        assert entry["severity"] in ("diagnostic", "stop")
        assert entry["description"]


def test_every_sample_diagnostic_code_resolves_to_a_real_registry_member():
    """The (str, Enum) choice means a typo in samples.yaml's diagnostic_codes/
    reason_code would silently just fail to match rather than raising -- this
    catches that class of typo explicitly rather than relying on outcome
    tests happening to notice a mismatch."""
    raw_entries = yaml.safe_load(DEFAULT_SAMPLES_PATH.read_text(encoding="utf-8"))
    valid_codes = {c.value for c in DiagnosticCode.all()}

    for entry in raw_entries:
        for code in entry["expected"].get("diagnostic_codes", []):
            assert code in valid_codes, f"{entry['id']}: {code!r} is not a registered DiagnosticCode"
        reason_code = entry["expected"].get("reason_code")
        if reason_code is not None:
            assert reason_code in valid_codes, f"{entry['id']}: reason_code {reason_code!r} is not registered"


# --- samples endpoints -------------------------------------------------------

def test_samples_list_endpoint(client):
    response = client.get("/samples")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(ALL_SAMPLE_IDS)
    assert {s["id"] for s in body} == set(ALL_SAMPLE_IDS)


def test_sample_detail_endpoint(client):
    response = client.get("/samples/auth_request_0100_ascii")
    assert response.status_code == 200
    assert response.json()["id"] == "auth_request_0100_ascii"


def test_sample_detail_404_for_unknown_id(client):
    response = client.get("/samples/does-not-exist")
    assert response.status_code == 404


# --- health / CORS ------------------------------------------------------

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_local_origin(client):
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_non_local_origin(client):
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers
