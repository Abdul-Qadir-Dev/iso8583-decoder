"""Shared diagnostic type.

Anomalies (unknown MTI digit, missing currency exponent, later: bitmap
mismatches, length disagreements, invalid BCD, trailing bytes) are
collected, not raised, so one bad field doesn't stop the rest of a
message from decoding.
"""

from dataclasses import dataclass


@dataclass
class Diagnostic:
    code: str       # short machine-readable tag, e.g. "mti_unknown_class"
    message: str    # human-readable explanation
