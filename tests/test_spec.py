import pytest
from pydantic import ValidationError

from iso8583_decoder.spec import DataType, FieldSpec, LengthType, load_spec
from tests.conftest import SPEC_PATH


def test_loads_generic_1987_spec():
    spec = load_spec(SPEC_PATH)
    assert spec.variant == "1987"
    assert 39 in spec.fields


def test_response_code_value_map_has_approved():
    spec = load_spec(SPEC_PATH)
    field_39 = spec.fields[39]
    assert field_39.value_map["00"] == "Approved"


def test_pan_is_variable_length():
    spec = load_spec(SPEC_PATH)
    pan = spec.fields[2]
    assert pan.length_type == LengthType.VARIABLE
    assert pan.length_digits == 2
    assert pan.length is None


def test_amount_is_fixed_length_numeric():
    spec = load_spec(SPEC_PATH)
    amount = spec.fields[4]
    assert amount.length_type == LengthType.FIXED
    assert amount.length == 12
    assert amount.data_type == DataType.NUMERIC


def test_fixed_field_without_length_is_rejected():
    with pytest.raises(ValidationError):
        FieldSpec(number=4, name="bad", data_type="n", length_type="fixed")


def test_variable_field_without_length_digits_is_rejected():
    with pytest.raises(ValidationError):
        FieldSpec(number=2, name="bad", data_type="n", length_type="variable")


def test_fixed_field_cannot_also_set_length_digits():
    with pytest.raises(ValidationError):
        FieldSpec(number=4, name="bad", data_type="n", length_type="fixed", length=12, length_digits=2)


def test_binary_field_cannot_have_value_map():
    with pytest.raises(ValidationError):
        FieldSpec(
            number=52, name="bad", data_type="b", length_type="fixed", length=8,
            value_map={"00": "nope"},
        )


def test_field_1_is_rejected_as_a_data_field():
    from iso8583_decoder.spec import MessageSpec

    with pytest.raises(ValidationError):
        MessageSpec(
            variant="1987",
            name="bad",
            fields={1: FieldSpec(number=1, name="bad", data_type="n", length_type="fixed", length=1)},
        )


def test_spec_key_must_match_field_number():
    from iso8583_decoder.spec import MessageSpec

    with pytest.raises(ValidationError):
        MessageSpec(
            variant="1987",
            name="bad",
            fields={3: FieldSpec(number=4, name="mismatched", data_type="n", length_type="fixed", length=12)},
        )
