"""The API's wire contract. Pydantic models here are deliberately separate
from the internal dataclasses (MtiDecodeResult, DecodeResult, Diagnostic,
FieldExplanation, Sample) -- internals can change shape without breaking
what's actually promised to a client, and vice versa. Nothing in api.py
returns an internal dataclass directly; everything goes through a
from_* constructor here first.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DecodeRequest(BaseModel):
    raw: str
    encoding: Literal["ascii", "binary"]  # required, no default -- same rule as decode_message()
    explain: bool = False
    reveal: bool = False  # threads render.py's reveal flag through; off by default, same reasoning


class MtiComponentResponse(BaseModel):
    digit: str
    meaning: str | None


class MtiResponse(BaseModel):
    raw: str
    version: MtiComponentResponse
    message_class: MtiComponentResponse
    function: MtiComponentResponse
    origin: MtiComponentResponse
    summary: str


class DiagnosticResponse(BaseModel):
    code: str
    severity: str
    field_number: int | None
    byte_offset: int | None
    message: str


class FieldResponse(BaseModel):
    field_number: int
    raw: str  # display value: masked/redacted per field sensitivity unless reveal=true was requested
    interpreted: str | None = None  # only populated when the request asked for explain=true


class DecodeResponse(BaseModel):
    mti: MtiResponse | None  # None only when the message couldn't be decoded even that far
    fields: list[FieldResponse]
    diagnostics: list[DiagnosticResponse]
    partial: bool
    stopped_at: str | None
    reason_code: str | None


class DiagnosticDefResponse(BaseModel):
    code: str
    severity: str
    description: str


class SampleExpectedResponse(BaseModel):
    partial: bool
    diagnostic_codes: list[str]
    stopped_at: str | None
    reason_code: str | None


class SampleResponse(BaseModel):
    id: str
    description: str
    transaction_type: str
    encoding: str
    raw: str
    expected: SampleExpectedResponse


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    detail: str
