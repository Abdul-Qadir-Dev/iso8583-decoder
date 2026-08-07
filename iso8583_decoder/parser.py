"""End-to-end decode: MTI -> bitmap -> field extraction, wired into one
entry point with diagnostics collected from all three stages.

encoding is required, never inferred from the message content -- a
wrong guess produces a plausible-looking wrong decode, which is
exactly the failure this tool exists to prevent.

ASCII mode: the whole message is literal text (digits are digit
characters, the bitmap is 16 hex-digit characters, binary fields are
hex-ASCII text). Binary mode: the whole message is a hex dump of raw
bytes (MTI as ASCII bytes, bitmap packed into 8 bytes, numeric fields
BCD-packed, alphanumeric fields as raw ASCII bytes). The bitmap
parser itself is reused unchanged between the two: 16 hex characters
mean the same 64 bits whether they arrived as literal message text or
as a hex dump of 8 packed bytes -- same nibble-order convention either
way, so there's nothing mode-specific about reading them.

A raw message that's structurally unreadable at the MTI level (wrong
length/encoding, non-numeric) or names an MTI version with no mapped
spec still raises -- there's nothing at all to return in either case,
not even a partial result. Every anomaly past that point either
continues (a Diagnostic gets added to the result) or stops (the
result comes back with partial=True, decoded_so_far holding whatever
was read before the stop, stopped_at naming where, and reason holding
the Diagnostic that caused it). Both kinds can appear in the same
result: a diagnostic means "something's wrong here but I kept going";
a partial result means "I stopped, and here's exactly where and why."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from .binary_extract import extract_fields_binary
from .bitmap import BitmapResult, parse_bitmap
from .diagnostics import Diagnostic
from .extract import ExtractResult, extract_fields
from .mti import MtiDecodeResult, MtiFormatError, decode_mti, load_spec_for_version


@dataclass
class DecodeResult:
    raw: str
    mti: MtiDecodeResult
    bitmap_primary_hex: str | None
    bitmap_secondary_hex: str | None
    decoded_so_far: dict[int, str]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    partial: bool = False
    stopped_at: str | None = None
    reason: Diagnostic | None = None


def decode_message(raw: str, encoding: Literal["ascii", "binary"]) -> DecodeResult:
    if encoding == "ascii":
        return _decode_ascii(raw)
    return _decode_binary(raw)


def _decode_ascii(raw: str) -> DecodeResult:
    mti_result = decode_mti(raw[:4])                       # raises MtiFormatError if unparseable
    spec = load_spec_for_version(mti_result.version.digit)  # raises UnsupportedVersionError if unmapped

    body_after_mti = raw[4:]
    bitmap_result = parse_bitmap(body_after_mti, known_fields=set(spec.fields.keys()))
    body_after_bitmap = body_after_mti[bitmap_result.consumed_chars:]

    return _assemble(raw, mti_result, bitmap_result,
                      lambda: extract_fields(body_after_bitmap, bitmap_result.present_fields, spec))


def _decode_binary(hex_dump: str) -> DecodeResult:
    mti_hex = hex_dump[:8]
    try:
        mti_ascii = bytes.fromhex(mti_hex).decode("ascii")
    except ValueError as exc:
        raise MtiFormatError(f"MTI hex prefix {mti_hex!r} isn't decodable as 4 ASCII bytes") from exc

    mti_result = decode_mti(mti_ascii)                       # raises MtiFormatError if unparseable
    spec = load_spec_for_version(mti_result.version.digit)   # raises UnsupportedVersionError if unmapped

    body_after_mti = hex_dump[8:]
    bitmap_result = parse_bitmap(body_after_mti, known_fields=set(spec.fields.keys()))
    body_after_bitmap = body_after_mti[bitmap_result.consumed_chars:]

    return _assemble(hex_dump, mti_result, bitmap_result,
                      lambda: extract_fields_binary(body_after_bitmap, bitmap_result.present_fields, spec))


def _assemble(
    raw: str,
    mti_result: MtiDecodeResult,
    bitmap_result: BitmapResult,
    run_extraction: Callable[[], ExtractResult],
) -> DecodeResult:
    diagnostics: list[Diagnostic] = list(mti_result.diagnostics)

    if bitmap_result.partial:
        # bitmap.py always appends exactly one diagnostic (the stop cause) last;
        # anything before it is a continue-anyway anomaly from primary parsing.
        stop_reason = bitmap_result.diagnostics[-1]
        diagnostics.extend(bitmap_result.diagnostics[:-1])
        stage = "primary_bitmap" if stop_reason.code.startswith("bitmap_primary") else "secondary_bitmap"
        return DecodeResult(
            raw=raw, mti=mti_result,
            bitmap_primary_hex=bitmap_result.primary_hex,
            bitmap_secondary_hex=bitmap_result.secondary_hex,
            decoded_so_far={},
            diagnostics=diagnostics,
            partial=True, stopped_at=stage, reason=stop_reason,
        )

    diagnostics.extend(bitmap_result.diagnostics)
    extract_result = run_extraction()
    diagnostics.extend(extract_result.diagnostics)

    if extract_result.stop is not None:
        return DecodeResult(
            raw=raw, mti=mti_result,
            bitmap_primary_hex=bitmap_result.primary_hex,
            bitmap_secondary_hex=bitmap_result.secondary_hex,
            decoded_so_far=extract_result.decoded_so_far,
            diagnostics=diagnostics,
            partial=True, stopped_at=extract_result.stop.stopped_at, reason=extract_result.stop.reason,
        )

    return DecodeResult(
        raw=raw, mti=mti_result,
        bitmap_primary_hex=bitmap_result.primary_hex,
        bitmap_secondary_hex=bitmap_result.secondary_hex,
        decoded_so_far=extract_result.decoded_so_far,
        diagnostics=diagnostics,
        partial=False, stopped_at=None, reason=None,
    )
