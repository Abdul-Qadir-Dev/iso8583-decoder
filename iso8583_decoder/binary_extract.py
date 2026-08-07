"""Binary/BCD-mode field extraction.

Input is a hex-dump string of the raw byte stream: 2 hex characters
per byte, uniformly. MTI text, the packed bitmap, BCD-packed numeric
data, and ASCII alphanumeric data are all just different ways of
interpreting bytes within that same hex string -- there's no point
where the representation switches from "text" to "hex", the whole
thing is a byte dump throughout.

Packing rules:
  - n (numeric) fields, and the length prefix of any variable-length
    field (regardless of that field's own data_type, since a length
    prefix is itself a numeric value), are BCD-packed: two decimal
    digits per byte. An odd digit count needs one pad nibble, and
    FieldSpec.bcd_pad says which end it's on.
  - an/ans/z fields stay one byte per character (ASCII), never packed.
  - b fields are raw bytes -- declared_length already means byte
    count, so no doubling like ASCII mode needs for hex-as-text.

A BCD nibble above 9 in a data position is a diagnostic (the field's
byte length is still known, so the offset stays trustworthy) with the
raw nibble kept in the message. The same problem in a length prefix
is a stop: an unreadable prefix means the field's byte length is
unknown, so nothing after it can be trusted either.

Diagnostic byte_offset here is local: byte position within `hex_dump`
(the caller's own input, starting right after the bitmap), already in
true bytes since that's this module's native unit -- parser.py just
adds the right base when assembling the final result, no /2 needed
here (that conversion is for bitmap.py's hex-character-native offsets
in binary mode, not this module's already-byte-native ones).
"""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import Diagnostic, DiagnosticCode
from .spec import BcdPad, DataType, LengthType, MessageSpec


@dataclass
class StopInfo:
    stopped_at: str
    reason: Diagnostic


@dataclass
class ExtractResult:
    decoded_so_far: dict[int, str]
    diagnostics: list[Diagnostic]
    stop: StopInfo | None


def _byte_count_for_digits(digit_count: int) -> int:
    return (digit_count + 1) // 2  # ceil(digit_count / 2)


def _nibbles(hex_bytes: str) -> list[int]:
    return [int(c, 16) for c in hex_bytes]


def _unpack_bcd(
    nibbles: list[int], digit_count: int, pad: BcdPad, field_number: int, byte_offset: int,
) -> tuple[str, list[Diagnostic]]:
    """nibbles may carry one extra pad nibble beyond digit_count, when digit_count is odd."""
    if digit_count % 2 == 1 and len(nibbles) > digit_count:
        digit_nibbles = nibbles[1:] if pad == BcdPad.LEADING else nibbles[:-1]
    else:
        digit_nibbles = nibbles  # even digit_count (no pad), or a truncated read with nothing to trim

    diagnostics: list[Diagnostic] = []
    chars = []
    for nib in digit_nibbles:
        if 0 <= nib <= 9:
            chars.append(str(nib))
        else:
            chars.append(format(nib, "x"))
            diagnostics.append(Diagnostic(
                code=DiagnosticCode.FIELD_INVALID_BCD_NIBBLE,
                message=f"field {field_number}: BCD nibble {nib:x} isn't a valid decimal digit (0-9)",
                field_number=field_number,
                byte_offset=byte_offset,
            ))
    return "".join(chars), diagnostics


def _hex_to_ascii(hex_str: str) -> str:
    return bytes.fromhex(hex_str).decode("ascii", errors="replace")


def extract_fields_binary(hex_dump: str, present_fields: list[int], spec: MessageSpec) -> ExtractResult:
    decoded: dict[int, str] = {}
    diagnostics: list[Diagnostic] = []
    pos = 0  # byte position; hex-dump character offset is pos * 2
    total_bytes = len(hex_dump) // 2

    def hex_slice(start_byte: int, nbytes: int) -> str:
        return hex_dump[start_byte * 2: (start_byte + nbytes) * 2]

    for field_number in present_fields:
        field_start = pos
        field_spec = spec.fields.get(field_number)
        if field_spec is None:
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
            declared_length: int = field_spec.length
        else:
            prefix_digits = field_spec.length_digits
            prefix_bytes = _byte_count_for_digits(prefix_digits)
            if total_bytes - pos < prefix_bytes:
                return ExtractResult(decoded, diagnostics, StopInfo(
                    stopped_at=f"field_{field_number}",
                    reason=Diagnostic(
                        code=DiagnosticCode.FIELD_LENGTH_PREFIX_TRUNCATED,
                        message=f"field {field_number}: message ends before its {prefix_digits}-digit "
                                f"BCD length prefix ({prefix_bytes} byte(s))",
                        field_number=field_number,
                        byte_offset=field_start,
                    ),
                ))
            prefix_str, prefix_diagnostics = _unpack_bcd(
                _nibbles(hex_slice(pos, prefix_bytes)), prefix_digits, field_spec.bcd_pad, field_number, field_start,
            )
            if prefix_diagnostics:
                # invalid BCD in a length prefix means the length itself can't be
                # trusted -- stop, don't guess at a numeric value from bad nibbles
                return ExtractResult(decoded, diagnostics, StopInfo(
                    stopped_at=f"field_{field_number}",
                    reason=Diagnostic(
                        code=DiagnosticCode.FIELD_LENGTH_PREFIX_INVALID_BCD,
                        message=f"field {field_number}: length prefix contains invalid BCD "
                                f"({'; '.join(d.message for d in prefix_diagnostics)})",
                        field_number=field_number,
                        byte_offset=field_start,
                    ),
                ))
            declared_length = int(prefix_str)
            pos += prefix_bytes

        if field_spec.data_type == DataType.NUMERIC:
            value_bytes = _byte_count_for_digits(declared_length)
        else:
            value_bytes = declared_length  # an/ans/z: 1 byte/char. b: already a byte count.

        available_bytes = total_bytes - pos
        take_bytes = min(value_bytes, available_bytes)

        if available_bytes < value_bytes:
            code = (DiagnosticCode.FIELD_VARIABLE_LENGTH_EXCEEDS_REMAINING
                    if field_spec.length_type == LengthType.VARIABLE
                    else DiagnosticCode.FIELD_FIXED_LENGTH_EXCEEDS_REMAINING)
            diagnostics.append(Diagnostic(
                code=code,
                message=f"field {field_number}: declared length needs {value_bytes} byte(s), "
                        f"only {available_bytes} remain in the message",
                field_number=field_number,
                byte_offset=field_start,
            ))

        value_start = pos
        value_hex = hex_slice(pos, take_bytes)
        pos += take_bytes

        if field_spec.data_type == DataType.NUMERIC:
            nibbles = _nibbles(value_hex)
            expected_digits = declared_length if take_bytes == value_bytes else len(nibbles)
            raw_value, bcd_diagnostics = _unpack_bcd(
                nibbles, expected_digits, field_spec.bcd_pad, field_number, value_start,
            )
            diagnostics.extend(bcd_diagnostics)
        elif field_spec.data_type == DataType.BINARY:
            raw_value = value_hex  # already the right representation: hex, 2 chars/byte
        else:  # an, ans, z
            raw_value = _hex_to_ascii(value_hex)

        decoded[field_number] = raw_value

    if pos < total_bytes:
        diagnostics.append(Diagnostic(
            code=DiagnosticCode.TRAILING_BYTES,
            message=f"{total_bytes - pos} unconsumed byte(s) remain after the last declared field",
            field_number=None,
            byte_offset=pos,
        ))

    return ExtractResult(decoded, diagnostics, None)
