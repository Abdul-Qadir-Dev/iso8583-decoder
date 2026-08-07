"""Field spec representation and loader.

A MessageSpec describes one processor's/variant's field layout: which
of the 128 possible data elements exist, how each is length-prefixed,
what data type it holds, and (optionally) how to explain its value in
plain language. Swapping processors means writing a new YAML file,
not touching parser code.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class DataType(str, Enum):
    NUMERIC = "n"                 # digits only, BCD-packed in binary mode
    ALPHANUMERIC = "an"
    ALPHANUMERIC_SPECIAL = "ans"
    TRACK2 = "z"
    BINARY = "b"                  # raw bytes, shown as hex, never interpreted


class LengthType(str, Enum):
    FIXED = "fixed"
    VARIABLE = "variable"


class FormatHint(str, Enum):
    NONE = "none"
    AMOUNT_MINOR_UNITS = "amount_minor_units"
    DATE_MMDD = "date_mmdd"
    TIME_HHMMSS = "time_hhmmss"
    EXPIRY_YYMM = "expiry_yymm"


class Sensitivity(str, Enum):
    NONE = "none"
    MASKED = "masked"       # partially shown by default, full value behind reveal
    REDACTED = "redacted"   # never shown, not even behind reveal


class MaskStrategy(str, Enum):
    """How to mask a value, when sensitivity == masked. Meaningless otherwise.

    Kept as spec data rather than a field-number check in the renderer,
    so which fields get which masking behavior stays fully swappable
    per processor, same as everything else in the spec file.
    """

    NONE = "none"
    DIRECT = "direct"           # the raw value is itself the sensitive data (PAN)
    TRACK_DATA = "track_data"   # a PAN is embedded inside track-format data


class BcdPad(str, Enum):
    """Which end carries the filler nibble when a BCD-packed digit count is odd.

    Binary mode only. Applies to a field's own value when data_type is n,
    and to the length prefix of any variable-length field regardless of
    that field's data_type (a length prefix is itself a numeric value).
    Leading is the common convention; processors differ, so it's a spec
    property rather than a hardcoded assumption.
    """

    LEADING = "leading"
    TRAILING = "trailing"


class FieldSpec(BaseModel):
    """One data element's definition.

    `length` and any length read from an LLVAR/LLLVAR prefix are counted
    in a unit that depends on data_type, not always bytes:
      - n (numeric):        digit count. ASCII mode = that many bytes.
                             Binary mode = BCD-packed, ceil(digits/2) bytes.
      - an/ans/z:            character count = byte count, always ASCII,
                             even in binary mode (only 'n' gets BCD-packed).
      - b (binary):          byte count. ASCII mode = 2 hex chars/byte.
                             Binary mode = that many raw bytes directly.
    """

    number: int = Field(ge=2, le=128)
    name: str
    data_type: DataType
    length_type: LengthType
    length: Optional[int] = None            # set when length_type == fixed
    length_digits: Optional[int] = None     # set when length_type == variable
    format_hint: FormatHint = FormatHint.NONE
    value_map: dict[str, str] = Field(default_factory=dict)
    bcd_pad: BcdPad = BcdPad.LEADING
    sensitivity: Sensitivity = Sensitivity.NONE
    mask_strategy: MaskStrategy = MaskStrategy.NONE

    @model_validator(mode="after")
    def check_sensitivity_consistency(self):
        if self.sensitivity == Sensitivity.MASKED and self.mask_strategy == MaskStrategy.NONE:
            raise ValueError(f"field {self.number}: sensitivity=masked needs a mask_strategy")
        if self.sensitivity != Sensitivity.MASKED and self.mask_strategy != MaskStrategy.NONE:
            raise ValueError(f"field {self.number}: mask_strategy only applies when sensitivity=masked")
        return self

    @model_validator(mode="after")
    def check_length_fields(self):
        if self.length_type == LengthType.FIXED:
            if self.length is None or self.length <= 0:
                raise ValueError(f"field {self.number}: fixed fields need a positive length")
            if self.length_digits is not None:
                raise ValueError(f"field {self.number}: fixed fields must not set length_digits")
        else:
            if self.length_digits not in (2, 3, 4):
                raise ValueError(f"field {self.number}: variable fields need length_digits in 2, 3, or 4")
            if self.length is not None:
                raise ValueError(f"field {self.number}: variable fields must not set length")
        return self

    @model_validator(mode="after")
    def check_value_map_only_for_short_codes(self):
        if self.value_map and self.data_type == DataType.BINARY:
            raise ValueError(f"field {self.number}: binary fields can't have a value_map, they're never interpreted")
        return self


class MessageSpec(BaseModel):
    variant: str   # "1987" or "1993"
    name: str
    fields: dict[int, FieldSpec]

    @model_validator(mode="after")
    def check_keys_match_field_numbers(self):
        for key, field_spec in self.fields.items():
            if key != field_spec.number:
                raise ValueError(f"spec key {key} does not match its field.number {field_spec.number}")
        if 1 in self.fields:
            raise ValueError("field 1 is the secondary bitmap presence indicator, it can't be a data field")
        return self


def load_spec(path: str | Path) -> MessageSpec:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    fields: dict[int, FieldSpec] = {}
    for key, values in raw.get("fields", {}).items():
        number = int(key)
        fields[number] = FieldSpec(number=number, **values)

    return MessageSpec(variant=raw["variant"], name=raw["name"], fields=fields)
