"""Render layer: the only place a decoded value becomes displayed text.

The parser (not built yet) will always carry the true decoded value
end to end -- masking is not applied during parsing. Every caller that
turns a field into human-readable output (API response, diagnostics
message, error text) goes through mask_value() or describe_field_error()
here instead of formatting raw_value directly, so masking can't be
forgotten in one call site while another gets it right.

Convention: for data_type == b (binary) fields, raw_value is always a
hex string (two characters per byte), regardless of whether the source
message was ASCII or binary-transport encoded. The parser normalizes
to that representation so this layer never has to know the transport.
"""

from __future__ import annotations

from .spec import DataType, FieldSpec, MaskStrategy, Sensitivity

MASK_CHAR = "*"
TRACK_SEPARATORS = ("^", "=", "D")  # track 1 uses ^, track 2 uses = (or D in some BCD conventions)


def _mask_pan(digits: str) -> str:
    """First 6, last 4, mask the middle. Too short to leave a safe gap -> mask all of it."""
    if len(digits) < 10:
        return MASK_CHAR * len(digits)
    middle_len = len(digits) - 10
    return digits[:6] + (MASK_CHAR * middle_len) + digits[-4:]


def _mask_track_data(raw: str) -> str:
    """Mask only the PAN embedded in track 1/2 data, not the surrounding fields.

    Track 1 looks like "B<PAN>^<NAME>^<...>"; track 2 like "<PAN>=<...>".
    If the format doesn't match anything recognized, fail closed: mask
    the entire value rather than risk showing an unrecognized PAN shape.
    """
    for sep in TRACK_SEPARATORS:
        if sep in raw:
            prefix, _, rest = raw.partition(sep)
            i = 0
            while i < len(prefix) and not prefix[i].isdigit():
                i += 1
            format_code, pan = prefix[:i], prefix[i:]
            if pan and pan.isdigit():
                return format_code + _mask_pan(pan) + sep + rest
    return MASK_CHAR * len(raw)


def mask_value(field_spec: FieldSpec, raw_value: str, reveal: bool = False) -> str:
    """The single entry point for turning a raw decoded value into displayed text."""
    if reveal:
        return raw_value

    if field_spec.sensitivity == Sensitivity.REDACTED:
        byte_count = len(raw_value) // 2 if field_spec.data_type == DataType.BINARY else len(raw_value)
        return f"[redacted, {byte_count} bytes]"

    if field_spec.sensitivity == Sensitivity.MASKED:
        if field_spec.mask_strategy == MaskStrategy.TRACK_DATA:
            return _mask_track_data(raw_value)
        return _mask_pan(raw_value)  # DIRECT

    return raw_value


def describe_field_error(field_spec: FieldSpec, raw_value: str, message: str, reveal: bool = False) -> str:
    """Build a diagnostic/error string about a field without leaking its raw value.

    This exists because the most common bug in tools like this isn't the
    happy path -- it's an error path that interpolates the raw value
    into an exception or log message and bypasses masking entirely.
    Diagnostics and error formatting (built later) should call this
    instead of building their own message strings around raw_value.
    """
    safe_value = mask_value(field_spec, raw_value, reveal=reveal)
    return f"field {field_spec.number} ({field_spec.name}): {message} [value: {safe_value}]"
