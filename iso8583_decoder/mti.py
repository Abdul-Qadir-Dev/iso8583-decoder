"""Structural MTI (Message Type Indicator) decoding.

MTI semantics are part of the ISO 8583 standard itself, not a
processor's field layout, so this decodes from digit position
directly rather than through the spec file. Unknown/reserved digit
values are anomalies, not exceptions: they're recorded as diagnostics
and decoding continues, because a support engineer needs to see the
rest of a message that has one bad digit in the MTI.

A completely malformed MTI (wrong length, non-numeric) is different:
there's no position to read a "reserved value" from, so that raises
instead of producing a best-effort result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .diagnostics import Diagnostic
from .spec import MessageSpec, load_spec

VERSION_MEANINGS = {
    "0": "1987",
    "1": "1993",
    "2": "1998",
    "9": "private use",
}

CLASS_MEANINGS = {
    "1": "Authorization",
    "2": "Financial",
    "3": "File action",
    "4": "Reversal/chargeback",
    "5": "Reconciliation",
    "6": "Administrative",
    "7": "Fee collection",
    "8": "Network management",
}

FUNCTION_MEANINGS = {
    "0": "Request",
    "1": "Request response",
    "2": "Advice",
    "3": "Advice response",
    "4": "Notification",
}

ORIGIN_MEANINGS = {
    "0": "Acquirer",
    "1": "Acquirer repeat",
    "2": "Issuer",
    "3": "Issuer repeat",
    "4": "Other",
}

# Which spec file backs each MTI version digit. Only 1987 exists so far;
# looking up an unmapped version raises a clear error, not a KeyError.
VERSION_SPEC_FILES = {
    "0": "1987_generic.yaml",
}

DEFAULT_SPEC_DIR = Path(__file__).resolve().parent.parent / "spec"


class MtiFormatError(ValueError):
    """MTI isn't 4 numeric digits -- can't structurally decode it at all."""


class UnsupportedVersionError(ValueError):
    """MTI version digit decoded fine, but no spec file is mapped to it."""


@dataclass
class MtiComponent:
    digit: str
    meaning: str | None  # None means reserved/unknown


@dataclass
class MtiDecodeResult:
    raw: str
    version: MtiComponent
    message_class: MtiComponent
    function: MtiComponent
    origin: MtiComponent
    summary: str
    diagnostics: list[Diagnostic] = field(default_factory=list)


def decode_mti(raw: str) -> MtiDecodeResult:
    if len(raw) != 4 or not raw.isdigit():
        raise MtiFormatError(f"MTI must be exactly 4 digits, got {raw!r}")

    diagnostics: list[Diagnostic] = []

    def decode_component(digit: str, table: dict[str, str], label: str) -> MtiComponent:
        meaning = table.get(digit)
        if meaning is None:
            diagnostics.append(Diagnostic(
                code=f"mti_unknown_{label}",
                message=f"MTI {label} digit {digit!r} is reserved/unknown",
            ))
        return MtiComponent(digit=digit, meaning=meaning)

    version = decode_component(raw[0], VERSION_MEANINGS, "version")
    message_class = decode_component(raw[1], CLASS_MEANINGS, "class")
    function = decode_component(raw[2], FUNCTION_MEANINGS, "function")
    origin = decode_component(raw[3], ORIGIN_MEANINGS, "origin")

    return MtiDecodeResult(
        raw=raw,
        version=version,
        message_class=message_class,
        function=function,
        origin=origin,
        summary=_build_summary(message_class, function, origin),
        diagnostics=diagnostics,
    )


def _build_summary(message_class: MtiComponent, function: MtiComponent, origin: MtiComponent) -> str:
    cls = message_class.meaning or f"unknown class ({message_class.digit})"
    fn = (function.meaning or f"unknown function ({function.digit})").lower()
    org = (origin.meaning or f"unknown origin ({origin.digit})").lower()
    return f"{cls} {fn} from {org}"


def load_spec_for_version(version_digit: str, spec_dir: Path = DEFAULT_SPEC_DIR) -> MessageSpec:
    """Resolve and load the field spec for an MTI version digit.

    Wired now even though only 1987 exists, so the decision point
    doesn't get bolted on later. An unmapped version is a clear error
    instead of a bare KeyError from the dict lookup.
    """
    try:
        filename = VERSION_SPEC_FILES[version_digit]
    except KeyError as exc:
        raise UnsupportedVersionError(
            f"no field spec available for MTI version digit {version_digit!r} "
            f"(supported: {sorted(VERSION_SPEC_FILES)})"
        ) from exc
    return load_spec(spec_dir / filename)
