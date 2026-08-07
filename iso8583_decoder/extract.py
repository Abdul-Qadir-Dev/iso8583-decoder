"""ASCII-mode field extraction.

Reads each present field's raw value from the message body per its
spec entry, advancing an offset through the string as it goes.
Binary/BCD-mode extraction is a later increment.

Two kinds of anomaly:
  - continue-anyway diagnostics: a value's characters don't match its
    declared data_type, a declared length runs past what's left in
    the message, or bytes remain after the last declared field. The
    offset is still known even though something about the data is off.
  - stop conditions: a variable field's length prefix can't be read
    at all (too few bytes for it, or it isn't numeric), or the field
    number isn't in the loaded spec so its length can't be determined
    at all. Either way there's no way to know where the *next* field
    would start, so extraction stops.

Diagnostic byte_offset here is local: character position within
`body` (the caller's own input, starting right after the bitmap), not
an absolute position in the full raw message -- parser.py adds the
right base when assembling the final result. Every diagnostic for a
given field uses that field's *starting* position, not the position
of whatever sub-part (prefix vs. value) actually triggered it, so
"where does this field begin" has one consistent answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import Diagnostic, DiagnosticCode
from .spec import DataType, FieldSpec, Interpretation, LengthType, MessageSpec

_HEX_DIGITS = set("0123456789abcdefABCDEF")


@dataclass
class StopInfo:
    stopped_at: str
    reason: Diagnostic


@dataclass
class ExtractResult:
    decoded_so_far: dict[int, str]
    diagnostics: list[Diagnostic]
    stop: StopInfo | None


def _char_length(field_spec: FieldSpec, declared_length: int) -> int:
    # Binary fields are transmitted as hex-ASCII in ASCII mode: 2 characters
    # per byte. Everything else (n/an/ans/z) is 1 character per declared unit.
    return declared_length * 2 if field_spec.data_type == DataType.BINARY else declared_length


def _matches_data_type(raw: str, data_type: DataType) -> bool:
    if data_type == DataType.NUMERIC:
        return raw.isdigit()
    if data_type == DataType.ALPHANUMERIC:
        return raw.isalnum()
    if data_type == DataType.BINARY:
        return len(raw) > 0 and all(c in _HEX_DIGITS for c in raw)
    return True  # ans/z: broad enough that strict validation isn't worth it here


def extract_fields(body: str, present_fields: list[int], spec: MessageSpec) -> ExtractResult:
    decoded: dict[int, str] = {}
    diagnostics: list[Diagnostic] = []
    pos = 0

    for field_number in present_fields:
        field_start = pos
        field_spec = spec.fields.get(field_number)
        if field_spec is None:
            # Already flagged by the bitmap parser (bitmap_field_not_in_spec).
            # Without a spec entry there's no length to read, so the offset
            # for anything after this field is unrecoverable.
            return ExtractResult(decoded, diagnostics, StopInfo(
                stopped_at=f"field_{field_number}",
                reason=Diagnostic(
                    code=DiagnosticCode.FIELD_SPEC_MISSING,
                    message=f"field {field_number} has no spec entry, its length is unknown "
                            f"so parsing can't continue past it",
                    field_number=field_number,
                    byte_offset=field_start,
                ),
            ))

        if field_spec.length_type == LengthType.FIXED:
            declared_length = field_spec.length
        else:
            prefix_len = field_spec.length_digits
            if len(body) - pos < prefix_len:
                return ExtractResult(decoded, diagnostics, StopInfo(
                    stopped_at=f"field_{field_number}",
                    reason=Diagnostic(
                        code=DiagnosticCode.FIELD_LENGTH_PREFIX_TRUNCATED,
                        message=f"field {field_number}: message ends before its "
                                f"{prefix_len}-digit length prefix",
                        field_number=field_number,
                        byte_offset=field_start,
                    ),
                ))
            prefix = body[pos:pos + prefix_len]
            if not prefix.isdigit():
                return ExtractResult(decoded, diagnostics, StopInfo(
                    stopped_at=f"field_{field_number}",
                    reason=Diagnostic(
                        code=DiagnosticCode.FIELD_LENGTH_PREFIX_UNREADABLE,
                        message=f"field {field_number}: length prefix {prefix!r} isn't numeric",
                        field_number=field_number,
                        byte_offset=field_start,
                    ),
                ))
            declared_length = int(prefix)
            pos += prefix_len

        char_length = _char_length(field_spec, declared_length)
        available = len(body) - pos
        take = min(char_length, available)

        if available < char_length:
            code = (DiagnosticCode.FIELD_VARIABLE_LENGTH_EXCEEDS_REMAINING
                    if field_spec.length_type == LengthType.VARIABLE
                    else DiagnosticCode.FIELD_FIXED_LENGTH_EXCEEDS_REMAINING)
            diagnostics.append(Diagnostic(
                code=code,
                message=f"field {field_number}: declared length needs {char_length} character(s), "
                        f"only {available} remain in the message",
                field_number=field_number,
                byte_offset=field_start,
            ))

        raw_value = body[pos:pos + take]
        pos += take
        decoded[field_number] = raw_value

        if not _matches_data_type(raw_value, field_spec.data_type):
            diagnostics.append(Diagnostic(
                code=DiagnosticCode.FIELD_DATA_TYPE_MISMATCH,
                message=f"field {field_number}: value doesn't match its declared "
                        f"data_type ({field_spec.data_type.value})",
                field_number=field_number,
                byte_offset=field_start,
            ))

        if field_spec.interpretation == Interpretation.RAW:
            byte_count = len(raw_value) // 2 if field_spec.data_type == DataType.BINARY else len(raw_value)
            unit = "bytes" if field_spec.data_type == DataType.BINARY else "characters"
            diagnostics.append(Diagnostic(
                code=DiagnosticCode.FIELD_RAW_NOT_INTERPRETED,
                message=f"field {field_number}: present, {byte_count} {unit}, "
                        f"processor-specific content not interpreted by this decoder",
                field_number=field_number,
                byte_offset=field_start,
            ))

    if pos < len(body):
        diagnostics.append(Diagnostic(
            code=DiagnosticCode.TRAILING_BYTES,
            message=f"{len(body) - pos} unconsumed character(s) remain after the last declared field",
            field_number=None,
            byte_offset=pos,
        ))

    return ExtractResult(decoded, diagnostics, None)
