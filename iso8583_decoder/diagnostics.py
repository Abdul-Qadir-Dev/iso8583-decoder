"""The diagnostic registry and shared Diagnostic type.

Diagnostic codes become a public contract the moment anything (API,
UI, README) is built against them, so nothing constructs one from a
bare string literal -- every call site references a DiagnosticCode
member. Codes are the stable identifier; human messages describe the
specific instance and may change freely.

Severity has exactly two levels, matching the two things that already
happen when something goes wrong: parsing either continues because
the byte offset is still trustworthy (DIAGNOSTIC), or halts because
it isn't (STOP, and the caller gets a partial result back). There's
no third state -- don't add one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    DIAGNOSTIC = "diagnostic"  # offset stays trustworthy, decoding continues
    STOP = "stop"               # offset becomes unknowable, decoding halts


class DiagnosticCode(str, Enum):
    """Every diagnostic code this decoder can emit. Also a str, so an
    existing `diagnostic.code == "some_string"` or `{d.code for d in ...}`
    comparison against plain strings keeps working unchanged -- the enum
    only forecloses *constructing* a Diagnostic from an unregistered code.

    .all() is the introspection entry point: one call returns every code
    with its severity and description, for the README and the API's
    error docs to read from instead of duplicating this list by hand.
    """

    def __new__(cls, code: str, severity: Severity, description: str):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.severity = severity
        obj.description = description
        return obj

    # -- MTI --
    MTI_UNKNOWN_VERSION = ("mti_unknown_version", Severity.DIAGNOSTIC,
        "MTI version digit isn't a recognized value (0=1987, 1=1993, 2=1998, 9=private use)")
    MTI_UNKNOWN_CLASS = ("mti_unknown_class", Severity.DIAGNOSTIC,
        "MTI message class digit isn't a recognized value (1-8)")
    MTI_UNKNOWN_FUNCTION = ("mti_unknown_function", Severity.DIAGNOSTIC,
        "MTI message function digit isn't a recognized value (0-4)")
    MTI_UNKNOWN_ORIGIN = ("mti_unknown_origin", Severity.DIAGNOSTIC,
        "MTI message origin digit isn't a recognized value (0-4)")

    # -- bitmap --
    BITMAP_FIELD_NOT_IN_SPEC = ("bitmap_field_not_in_spec", Severity.DIAGNOSTIC,
        "a bitmap bit is set for a field number the loaded spec doesn't define")
    BITMAP_TERTIARY_BIT_SET = ("bitmap_tertiary_bit_set", Severity.DIAGNOSTIC,
        "bit 65 is set, which would indicate a tertiary bitmap (fields 129-192); out of scope for this decoder")
    BITMAP_PRIMARY_TOO_SHORT = ("bitmap_primary_too_short", Severity.STOP,
        "message is too short to contain a primary bitmap")
    BITMAP_PRIMARY_NON_HEX = ("bitmap_primary_non_hex", Severity.STOP,
        "primary bitmap contains characters that aren't valid hex")
    BITMAP_SECONDARY_MISSING = ("bitmap_secondary_missing", Severity.STOP,
        "bit 1 indicated a secondary bitmap, but the message doesn't contain one")
    BITMAP_SECONDARY_NON_HEX = ("bitmap_secondary_non_hex", Severity.STOP,
        "secondary bitmap contains characters that aren't valid hex")

    # -- field extraction (ascii and binary) --
    FIELD_SPEC_MISSING = ("field_spec_missing", Severity.STOP,
        "a present field has no entry in the loaded spec, so its length is unknown")
    FIELD_LENGTH_PREFIX_TRUNCATED = ("field_length_prefix_truncated", Severity.STOP,
        "the message ends before a variable field's length prefix is complete")
    FIELD_LENGTH_PREFIX_UNREADABLE = ("field_length_prefix_unreadable", Severity.STOP,
        "a length prefix (ASCII mode) contains non-numeric characters")
    FIELD_LENGTH_PREFIX_INVALID_BCD = ("field_length_prefix_invalid_bcd", Severity.STOP,
        "a length prefix (binary mode) contains a BCD nibble above 9")
    FIELD_VARIABLE_LENGTH_EXCEEDS_REMAINING = ("field_variable_length_exceeds_remaining", Severity.DIAGNOSTIC,
        "a variable field's declared length runs past what's left in the message")
    FIELD_FIXED_LENGTH_EXCEEDS_REMAINING = ("field_fixed_length_exceeds_remaining", Severity.DIAGNOSTIC,
        "a fixed field's declared length runs past what's left in the message")
    FIELD_DATA_TYPE_MISMATCH = ("field_data_type_mismatch", Severity.DIAGNOSTIC,
        "a field's decoded value doesn't match its declared data_type")
    FIELD_INVALID_BCD_NIBBLE = ("field_invalid_bcd_nibble", Severity.DIAGNOSTIC,
        "a BCD nibble in a data field is above 9")
    TRAILING_BYTES = ("trailing_bytes", Severity.DIAGNOSTIC,
        "bytes/characters remain unconsumed after the last declared field")

    # -- interpretation layer (amount formatting; see explain.py) --
    AMOUNT_CURRENCY_MISSING = ("amount_currency_missing", Severity.DIAGNOSTIC,
        "field 4 is present without field 49; the amount can't be formatted, only shown in minor units")
    AMOUNT_CURRENCY_UNKNOWN = ("amount_currency_unknown", Severity.DIAGNOSTIC,
        "field 49's currency code isn't in the exponent table; the amount can't be formatted")

    @classmethod
    def all(cls) -> list["DiagnosticCode"]:
        return list(cls)


@dataclass
class Diagnostic:
    code: DiagnosticCode
    message: str
    field_number: int | None = None
    byte_offset: int | None = None

    def __post_init__(self):
        # DiagnosticCode is a str subclass, so a plain string that happens to
        # match a registered code's value would otherwise sail through here
        # silently -- require the actual enum member, not just the right text.
        if not isinstance(self.code, DiagnosticCode):
            raise ValueError(
                f"Diagnostic.code must be a DiagnosticCode member, not {self.code!r} "
                f"({type(self.code).__name__}) -- construct it from the registry, "
                f"never from a string literal"
            )

    @property
    def severity(self) -> Severity:
        return self.code.severity
