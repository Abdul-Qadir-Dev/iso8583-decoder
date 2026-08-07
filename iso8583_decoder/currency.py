"""Currency-aware formatting for field 4 (Amount, Transaction).

Field 4 is transmitted as an integer count of minor units, but how
many digits belong after the decimal point depends on field 49's
currency code: most currencies use 2, a few (JPY, KRW, ...) use 0,
and a few (BHD, KWD, ...) use 3. Formatting field 4 without reading
field 49 gives a wrong answer for anything outside the 2-exponent
majority -- and it's a *plausible-looking* wrong answer, which is
worse than an obviously broken one.

If field 49 is missing or its code isn't in the table, this does not
fall back to assuming 2. It reports the amount in minor units, marks
the result as assumed rather than resolved, and raises a diagnostic.
Guessing here is exactly the class of silent wrong answer this tool
exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from .diagnostics import Diagnostic

DEFAULT_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "iso4217_exponents.yaml"


def load_currency_exponents(path: Path = DEFAULT_TABLE_PATH) -> dict[str, int]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(code): int(exponent) for code, exponent in raw.items()}


@dataclass
class AmountResult:
    minor_units: int
    formatted: str
    currency_code: str | None    # field 49's raw value, if present
    exponent_used: int | None    # None when we couldn't resolve one
    assumed: bool                # True if formatted is minor-units fallback, not a real conversion
    diagnostics: list[Diagnostic] = field(default_factory=list)


def format_amount(decoded_fields: dict[int, str], exponents: dict[str, int]) -> AmountResult:
    """decoded_fields is {field_number: raw_value}. Field 4 must be present; field 49 may not be."""
    minor_units = int(decoded_fields[4])
    currency_code = decoded_fields.get(49)

    if currency_code is None:
        return AmountResult(
            minor_units=minor_units,
            formatted=str(minor_units),
            currency_code=None,
            exponent_used=None,
            assumed=True,
            diagnostics=[Diagnostic(
                code="amount_currency_missing",
                message="field 4 present without field 49; showing minor units, exponent not assumed",
            )],
        )

    exponent = exponents.get(currency_code)
    if exponent is None:
        return AmountResult(
            minor_units=minor_units,
            formatted=str(minor_units),
            currency_code=currency_code,
            exponent_used=None,
            assumed=True,
            diagnostics=[Diagnostic(
                code="amount_currency_unknown",
                message=f"field 49 currency code {currency_code!r} not in the exponent table; "
                        f"showing minor units, exponent not assumed",
            )],
        )

    return AmountResult(
        minor_units=minor_units,
        formatted=_apply_exponent(minor_units, exponent),
        currency_code=currency_code,
        exponent_used=exponent,
        assumed=False,
        diagnostics=[],
    )


def _apply_exponent(minor_units: int, exponent: int) -> str:
    if exponent == 0:
        return str(minor_units)
    value = Decimal(minor_units) / (Decimal(10) ** exponent)
    return f"{value:.{exponent}f}"
