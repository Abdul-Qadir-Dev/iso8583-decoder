"""Plain-language field explanations: a lazy, separate layer on top of
a decoded message. Interpretation never replaces or mutates a decoded
value -- FieldExplanation always carries `raw` untouched, exactly what
extraction produced, alongside whatever plain-language `interpreted`
text could be built from it. A support engineer must always be able
to see the bytes that actually arrived.

This is display-of-meaning, not display-safety: masking/redaction for
sensitive fields (PAN, PIN block) already lives in render.py and isn't
duplicated here. A caller combines both when building a UI-facing
response -- explain a field's meaning, separately decide how much of
its raw value is safe to show.

Nothing here runs during parsing. decode_message() succeeds or fails
identically whether or not anyone ever calls explain_fields() on its
result -- interpretation is computed only when asked for, and a
failure interpreting one field never fails the whole call: it degrades
that field to `interpreted=None` and moves on, same as an unmapped
code degrades to a labeled "unmapped" string rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .currency import format_amount, load_currency_exponents
from .diagnostics import Diagnostic
from .spec import FieldSpec, FormatHint, MessageSpec

_PROCESSING_CODE_PATH = Path(__file__).resolve().parent.parent / "spec" / "processing_code_meanings.yaml"
_processing_code_meanings = yaml.safe_load(_PROCESSING_CODE_PATH.read_text(encoding="utf-8"))
_TRANSACTION_TYPES: dict[str, str] = _processing_code_meanings["transaction_type"]
_ACCOUNT_TYPES: dict[str, str] = _processing_code_meanings["account_type"]


@dataclass
class FieldExplanation:
    field_number: int
    raw: str                    # never mutated -- exactly what decoded_so_far had
    interpreted: str | None     # None means "nothing to interpret for this field", not a failure


@dataclass
class ExplainedFields:
    fields: dict[int, FieldExplanation]
    diagnostics: list[Diagnostic] = field(default_factory=list)


def explain_fields(
    decoded_fields: dict[int, str],
    spec: MessageSpec,
    currency_exponents: dict[str, int] | None = None,
) -> ExplainedFields:
    """decoded_fields is the decode result's decoded_so_far, unchanged. Works
    fine on a partial decode too -- explains whatever was actually decoded."""
    exponents = currency_exponents if currency_exponents is not None else load_currency_exponents()

    fields: dict[int, FieldExplanation] = {}
    diagnostics: list[Diagnostic] = []

    for field_number, raw in decoded_fields.items():
        field_spec = spec.fields.get(field_number)
        try:
            interpreted, field_diagnostics = _explain_one(field_number, raw, field_spec, decoded_fields, exponents)
        except Exception:
            # An explanation lookup failing must never turn a successful decode
            # into a failed one -- degrade this one field, not the whole call.
            interpreted, field_diagnostics = None, []

        fields[field_number] = FieldExplanation(field_number=field_number, raw=raw, interpreted=interpreted)
        diagnostics.extend(field_diagnostics)

    return ExplainedFields(fields=fields, diagnostics=diagnostics)


def _explain_one(
    field_number: int, raw: str, field_spec: FieldSpec | None,
    decoded_fields: dict[int, str], exponents: dict[str, int],
) -> tuple[str | None, list[Diagnostic]]:
    if field_spec is None:
        return None, []

    if field_number == 3:
        return _explain_processing_code(raw), []

    if field_number == 4:
        return _explain_amount(decoded_fields, exponents)

    if field_number == 49:
        return _explain_currency_code(raw, exponents), []

    if field_spec.format_hint != FormatHint.NONE:
        return _format_temporal(raw, field_spec.format_hint), []

    if field_spec.value_map:
        return field_spec.value_map.get(raw, f"unmapped code: {raw!r}"), []

    return None, []


def _explain_processing_code(raw: str) -> str:
    if len(raw) != 6:
        return f"unmapped: processing code {raw!r} isn't 6 digits"
    txn_type, from_account, to_account = raw[0:2], raw[2:4], raw[4:6]
    txn_meaning = _TRANSACTION_TYPES.get(txn_type, f"unmapped code {txn_type!r}")
    from_meaning = _ACCOUNT_TYPES.get(from_account, f"unmapped code {from_account!r}")
    to_meaning = _ACCOUNT_TYPES.get(to_account, f"unmapped code {to_account!r}")
    return f"{txn_meaning}; from account: {from_meaning}; to account: {to_meaning}"


def _explain_amount(decoded_fields: dict[int, str], exponents: dict[str, int]) -> tuple[str, list[Diagnostic]]:
    amount_result = format_amount(decoded_fields, exponents)
    if amount_result.assumed:
        interpreted = f"{amount_result.formatted} (minor units -- currency exponent not determined)"
    else:
        interpreted = f"{amount_result.formatted} {amount_result.currency_code}"
    return interpreted, amount_result.diagnostics


def _explain_currency_code(raw: str, exponents: dict[str, int]) -> str:
    exponent = exponents.get(raw)
    if exponent is None:
        return f"unmapped currency code: {raw!r}"
    return f"minor-unit exponent {exponent}"


def _format_temporal(raw: str, hint: FormatHint) -> str | None:
    if hint == FormatHint.DATE_MMDD and len(raw) == 4:
        return f"{raw[0:2]}-{raw[2:4]} (year not present in message)"
    if hint == FormatHint.TIME_HHMMSS and len(raw) == 6:
        return f"{raw[0:2]}:{raw[2:4]}:{raw[4:6]}"
    if hint == FormatHint.DATETIME_MMDDHHMMSS and len(raw) == 10:
        return f"{raw[0:2]}-{raw[2:4]} {raw[4:6]}:{raw[6:8]}:{raw[8:10]} (year not present in message)"
    if hint == FormatHint.EXPIRY_YYMM and len(raw) == 4:
        return f"20{raw[0:2]}-{raw[2:4]}"
    return None
