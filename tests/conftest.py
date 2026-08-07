from pathlib import Path

import pytest

from iso8583_decoder.spec import load_spec

SPEC_PATH = Path(__file__).resolve().parent.parent / "spec" / "1987_generic.yaml"


@pytest.fixture
def spec():
    return load_spec(SPEC_PATH)
