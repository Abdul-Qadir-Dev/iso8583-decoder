"""The sample message library: one place holding realistic ISO 8583
messages, so tests, the API, the web UI demo, and the README all draw
from the same source instead of each hand-building messages.

Structured as data, same principle as FieldSpec: samples/messages.yaml
holds fully-formed raw message strings plus each one's declared
expected decode outcome. Nothing is computed at load time -- a
message's raw bytes are authored once (built the same way the parser
tests build theirs, then round-tripped through decode_message() to
confirm they actually produce the declared outcome) and frozen as a
literal string. A dynamic "build from field values" loader was
considered and rejected for this increment: it would need a real
bidirectional encoder living in the production package, and the
malformed samples can't be produced that way regardless, since being
malformed is the point.

load_samples() and get_sample() are the only way anything reads this
file -- nothing else should touch samples/messages.yaml directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

DEFAULT_SAMPLES_PATH = Path(__file__).resolve().parent.parent / "samples" / "messages.yaml"


@dataclass(frozen=True)
class ExpectedOutcome:
    partial: bool
    diagnostic_codes: frozenset[str] = frozenset()  # exact set of codes expected; ignores counts/order
    stopped_at: str | None = None                    # set only when partial
    reason_code: str | None = None                    # set only when partial


@dataclass(frozen=True)
class Sample:
    id: str
    description: str
    transaction_type: str
    encoding: Literal["ascii", "binary"]
    raw: str
    expected: ExpectedOutcome


def _load_expected(raw: dict) -> ExpectedOutcome:
    return ExpectedOutcome(
        partial=raw["partial"],
        diagnostic_codes=frozenset(raw.get("diagnostic_codes", [])),
        stopped_at=raw.get("stopped_at"),
        reason_code=raw.get("reason_code"),
    )


def load_samples(path: Path = DEFAULT_SAMPLES_PATH) -> list[Sample]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Sample(
            id=entry["id"],
            description=entry["description"],
            transaction_type=entry["transaction_type"],
            encoding=entry["encoding"],
            raw=entry["raw"],
            expected=_load_expected(entry["expected"]),
        )
        for entry in entries
    ]


def get_sample(sample_id: str, path: Path = DEFAULT_SAMPLES_PATH) -> Sample:
    for sample in load_samples(path):
        if sample.id == sample_id:
            return sample
    raise KeyError(f"no sample with id {sample_id!r}")
