import pytest

from iso8583_decoder.diagnostics import Diagnostic, DiagnosticCode, Severity


def test_severity_has_exactly_two_levels():
    assert {s.value for s in Severity} == {"diagnostic", "stop"}


def test_registry_is_introspectable():
    codes = DiagnosticCode.all()
    assert len(codes) > 0
    for code in codes:
        assert isinstance(code.severity, Severity)
        assert isinstance(code.description, str) and code.description


def test_every_code_is_unique():
    codes = [c.value for c in DiagnosticCode.all()]
    assert len(codes) == len(set(codes))


def test_diagnostic_code_still_compares_equal_to_its_plain_string():
    # existing call sites compare diagnostic.code == "some_string" and build
    # sets like {d.code for d in ...} against plain-string samples.yaml data;
    # both must keep working now that code is an enum, not a bare string
    code = DiagnosticCode.MTI_UNKNOWN_VERSION
    assert code == "mti_unknown_version"
    assert code in {"mti_unknown_version", "other"}
    assert {code} == frozenset({"mti_unknown_version"})
    assert code.startswith("mti_unknown")


def test_diagnostic_severity_is_derived_from_its_code():
    stop_diag = Diagnostic(code=DiagnosticCode.BITMAP_PRIMARY_TOO_SHORT, message="x")
    continue_diag = Diagnostic(code=DiagnosticCode.TRAILING_BYTES, message="x")
    assert stop_diag.severity == Severity.STOP
    assert continue_diag.severity == Severity.DIAGNOSTIC


def test_diagnostic_requires_a_registered_code_not_an_arbitrary_string():
    with pytest.raises(ValueError):
        Diagnostic(code="not_a_real_code", message="x")  # type: ignore[arg-type]
