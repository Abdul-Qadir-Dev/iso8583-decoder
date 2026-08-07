"""ASCII-mode end-to-end decode: MTI -> bitmap -> field extraction, wired
into one entry point with diagnostics collected from all three stages.
Binary/BCD-mode messages are a later increment.

A raw message that's structurally unreadable at the MTI level (wrong
length, non-numeric) or names an MTI version with no mapped spec still
raises -- there's nothing at all to return in either case, not even a
partial result. Every anomaly past that point either continues (a
Diagnostic gets added to the result) or stops (the result comes back
with partial=True, decoded_so_far holding whatever was read before the
stop, stopped_at naming where, and reason holding the Diagnostic that
caused it). Both kinds can appear in the same result: a diagnostic
means "something's wrong here but I kept going"; a partial result means
"I stopped, and here's exactly where and why."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bitmap import parse_bitmap
from .diagnostics import Diagnostic
from .extract import extract_fields
from .mti import MtiDecodeResult, decode_mti, load_spec_for_version


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


def decode_message(raw: str) -> DecodeResult:
    mti_result = decode_mti(raw[:4])                       # raises MtiFormatError if unparseable
    spec = load_spec_for_version(mti_result.version.digit)  # raises UnsupportedVersionError if unmapped

    diagnostics: list[Diagnostic] = list(mti_result.diagnostics)
    body_after_mti = raw[4:]

    bitmap_result = parse_bitmap(body_after_mti, known_fields=set(spec.fields.keys()))

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
    body_after_bitmap = body_after_mti[bitmap_result.consumed_chars:]
    extract_result = extract_fields(body_after_bitmap, bitmap_result.present_fields, spec)
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
