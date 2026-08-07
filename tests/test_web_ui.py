import re

import pytest
from fastapi.testclient import TestClient

from iso8583_decoder.api import create_app
from iso8583_decoder.samples import load_samples

# Standard, publicly-documented test PANs used elsewhere in this project
# (sample library, fixtures). Anything else that looks like a PAN showing up
# in the static page source would mean sample data got hardcoded into the
# UI instead of being loaded from the API at runtime.
STANDARD_TEST_PANS = {"4111111111111111", "5555555555554444"}


@pytest.fixture
def client():
    return TestClient(create_app())


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>ISO 8583 Message Decoder</title>" in response.text


def test_index_page_has_no_hardcoded_pan_beyond_standard_test_ranges(client):
    response = client.get("/")
    body = response.text
    # any run of 12-19 digits is PAN-shaped (ISO/IEC 7812)
    candidates = re.findall(r"\b\d{12,19}\b", body)
    unexpected = [c for c in candidates if c not in STANDARD_TEST_PANS]
    assert unexpected == [], f"page source contains unexpected PAN-shaped digit runs: {unexpected}"


def test_index_page_contains_no_pan_shaped_digit_runs_at_all():
    """Stronger check than the fixture-based one above: the page shouldn't
    hardcode sample data at all, since samples are loaded from GET /samples
    at runtime -- so no 12-19 digit run should appear in the source file,
    not even one matching a standard test PAN."""
    from iso8583_decoder.api import INDEX_HTML_PATH

    source = INDEX_HTML_PATH.read_text(encoding="utf-8")
    candidates = re.findall(r"\b\d{12,19}\b", source)
    assert candidates == [], f"page source hardcodes PAN-shaped digit runs: {candidates}"


def test_index_page_does_not_hardcode_any_sample_message_content():
    """Every sample's raw message must come from the API, not be embedded
    directly in the static HTML."""
    from iso8583_decoder.api import INDEX_HTML_PATH

    source = INDEX_HTML_PATH.read_text(encoding="utf-8")
    for sample in load_samples():
        assert sample.raw not in source, f"{sample.id}'s raw message is hardcoded in the page"


def test_specs_endpoint_used_by_the_ui(client):
    response = client.get("/specs")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert body[0]["version_digit"] == "0"
    assert body[0]["variant"] == "1987"


def test_field_response_includes_name_for_the_ui_table(client):
    sample = next(s for s in load_samples() if s.id == "auth_request_0100_ascii")
    response = client.post("/decode", json={"raw": sample.raw, "encoding": sample.encoding})
    body = response.json()
    field_2 = next(f for f in body["fields"] if f["field_number"] == 2)
    assert field_2["name"] == "Primary Account Number"
