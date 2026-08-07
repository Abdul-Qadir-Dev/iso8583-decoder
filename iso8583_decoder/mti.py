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

The four per-position meaning tables (version/class/function/origin)
are loaded from spec/mti_meanings.yaml rather than kept as Python dict
literals -- they're value maps like everything else this decoder
interprets, so they're data. The *structural* decode -- which digit
position means what, walking them and building the plain-language
summary -- stays as code here, since that's standard-level logic, not
data a processor spec would swap out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .diagnostics import Diagnostic, DiagnosticCode
from .spec import MessageSpec, load_spec

DEFAULT_SPEC_DIR = Path(__file__).resolve().parent.parent / "spec"
_MEANINGS_PATH = DEFAULT_SPEC_DIR / "mti_meanings.yaml"

_meanings = yaml.safe_load(_MEANINGS_PATH.read_text(encoding="utf-8"))
VERSION_MEANINGS: dict[str, str] = _meanings["version"]
CLASS_MEANINGS: dict[str, str] = _meanings["message_class"]
FUNCTION_MEANINGS: dict[str, str] = _meanings["function"]
ORIGIN_MEANINGS: dict[str, str] = _meanings["origin"]

# Which spec file backs each MTI version digit. Only 1987 exists so far;
# looking up an unmapped version raises a clear error, not a KeyError.
VERSION_SPEC_FILES = {
    "0": "1987_generic.yaml",
}


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

    def decode_component(digit: str, table: dict[str, str], label: str, code: DiagnosticCode, offset: int) -> MtiComponent:
        meaning = table.get(digit)
        if meaning is None:
            diagnostics.append(Diagnostic(
                code=code,
                message=f"MTI {label} digit {digit!r} is reserved/unknown",
                field_number=None,
                byte_offset=offset,  # MTI is always the first 4 bytes of any message
            ))
        return MtiComponent(digit=digit, meaning=meaning)

    version = decode_component(raw[0], VERSION_MEANINGS, "version", DiagnosticCode.MTI_UNKNOWN_VERSION, 0)
    message_class = decode_component(raw[1], CLASS_MEANINGS, "class", DiagnosticCode.MTI_UNKNOWN_CLASS, 1)
    function = decode_component(raw[2], FUNCTION_MEANINGS, "function", DiagnosticCode.MTI_UNKNOWN_FUNCTION, 2)
    origin = decode_component(raw[3], ORIGIN_MEANINGS, "origin", DiagnosticCode.MTI_UNKNOWN_ORIGIN, 3)

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
