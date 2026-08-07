"""ASCII-mode bitmap parsing.

Primary bitmap: 16 hex characters (64 bits) covering fields 1-64.
Bit 1 is not a data field -- it indicates whether a secondary bitmap
(a further 16 hex characters, fields 65-128) follows.

Most anomalies here are diagnostics: decoding continues. Three are
not, because they make every subsequent byte offset untrustworthy
rather than just wrong in one field:
  - the primary bitmap isn't 16 readable hex characters
  - bit 1 is set but no secondary bitmap is actually present
  - the secondary bitmap (once its presence is confirmed) isn't
    16 readable hex characters
In those three cases parsing stops and the result is marked partial,
carrying whatever was decoded up to that point plus the reason it
stopped -- not a best-effort guess at what comes after.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .diagnostics import Diagnostic

_HEX_DIGITS = set("0123456789abcdefABCDEF")


@dataclass
class BitmapResult:
    present_fields: list[int]        # ascending, excludes control bits (1, and 65 when it's a tertiary indicator)
    primary_hex: str
    secondary_hex: str | None
    consumed_chars: int              # how much of the message the bitmap(s) occupied
    partial: bool
    partial_reason: str | None
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _is_hex(s: str) -> bool:
    return len(s) > 0 and all(c in _HEX_DIGITS for c in s)


def _set_bit_positions(hex_str: str, base_field: int) -> list[int]:
    """Field numbers whose bit is 1, ascending. Each hex char is 4 bits, MSB first."""
    positions = []
    for i, ch in enumerate(hex_str):
        nibble = int(ch, 16)
        for offset in range(4):
            if (nibble >> (3 - offset)) & 1:
                positions.append(base_field + i * 4 + offset)
    return positions


def _flag_unknown_fields(fields: list[int], known_fields: set[int], diagnostics: list[Diagnostic]) -> None:
    for f in fields:
        if f not in known_fields:
            diagnostics.append(Diagnostic(
                code="bitmap_field_not_in_spec",
                message=f"bit set for field {f}, which is not defined in the loaded spec",
            ))


def _stopped(
    code: str,
    reason: str,
    diagnostics: list[Diagnostic],
    primary_hex: str,
    secondary_hex: str | None = None,
    present_fields: list[int] | None = None,
    consumed_chars: int = 0,
) -> BitmapResult:
    diagnostics.append(Diagnostic(code=code, message=reason))
    return BitmapResult(
        present_fields=present_fields or [],
        primary_hex=primary_hex,
        secondary_hex=secondary_hex,
        consumed_chars=consumed_chars,
        partial=True,
        partial_reason=reason,
        diagnostics=diagnostics,
    )


def parse_bitmap(remaining: str, known_fields: set[int]) -> BitmapResult:
    """remaining is the message body starting at the primary bitmap. known_fields
    is the set of field numbers defined in the loaded spec, used to flag bits set
    for fields the spec doesn't know about."""
    diagnostics: list[Diagnostic] = []

    if len(remaining) < 16:
        return _stopped(
            "bitmap_primary_too_short",
            "message is too short to contain a primary bitmap (need 16 hex characters)",
            diagnostics, primary_hex=remaining,
        )

    primary_hex = remaining[:16]
    if not _is_hex(primary_hex):
        return _stopped(
            "bitmap_primary_non_hex",
            "primary bitmap contains non-hex characters, field offsets can't be trusted",
            diagnostics, primary_hex=primary_hex,
        )

    primary_bits = _set_bit_positions(primary_hex, base_field=1)
    secondary_indicated = 1 in primary_bits
    present_fields = [f for f in primary_bits if f != 1]
    _flag_unknown_fields(present_fields, known_fields, diagnostics)

    if not secondary_indicated:
        return BitmapResult(
            present_fields=present_fields, primary_hex=primary_hex, secondary_hex=None,
            consumed_chars=16, partial=False, partial_reason=None, diagnostics=diagnostics,
        )

    tail = remaining[16:32]
    if len(tail) < 16:
        return _stopped(
            "bitmap_secondary_missing",
            "bit 1 indicated a secondary bitmap, but the message doesn't contain one; "
            "field offsets from here on can't be trusted",
            diagnostics, primary_hex=primary_hex, present_fields=present_fields, consumed_chars=16,
        )

    if not _is_hex(tail):
        return _stopped(
            "bitmap_secondary_non_hex",
            "secondary bitmap contains non-hex characters, field offsets can't be trusted",
            diagnostics, primary_hex=primary_hex, secondary_hex=tail,
            present_fields=present_fields, consumed_chars=16,
        )

    secondary_bits = _set_bit_positions(tail, base_field=65)
    if 65 in secondary_bits:
        diagnostics.append(Diagnostic(
            code="bitmap_tertiary_bit_set",
            message="bit 65 set; would indicate a tertiary bitmap (fields 129-192), out of scope for this decoder",
        ))
        secondary_bits = [f for f in secondary_bits if f != 65]

    _flag_unknown_fields(secondary_bits, known_fields, diagnostics)
    present_fields = present_fields + secondary_bits

    return BitmapResult(
        present_fields=present_fields, primary_hex=primary_hex, secondary_hex=tail,
        consumed_chars=32, partial=False, partial_reason=None, diagnostics=diagnostics,
    )
