import pytest
from pydantic import ValidationError

from iso8583_decoder.spec import DataType, FieldSpec, Interpretation, LengthType, load_spec
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


def test_field_55_is_binary_raw_interpretation():
    spec = load_spec(SPEC_PATH)
    field_55 = spec.fields[55]
    assert field_55.data_type == DataType.BINARY
    assert field_55.length_type.value == "variable"
    assert field_55.length_digits == 3
    assert field_55.interpretation == Interpretation.RAW


def test_fields_48_and_60_to_63_are_ans_raw_interpretation():
    spec = load_spec(SPEC_PATH)
    for number in (48, 60, 61, 62, 63):
        field_spec = spec.fields[number]
        assert field_spec.data_type == DataType.ALPHANUMERIC_SPECIAL, number
        assert field_spec.length_digits == 3, number
        assert field_spec.interpretation == Interpretation.RAW, number


def test_interpretation_raw_cannot_also_declare_a_value_map():
    with pytest.raises(ValidationError):
        FieldSpec(
            number=48, name="bad", data_type="ans", length_type="variable", length_digits=3,
            interpretation=Interpretation.RAW, value_map={"00": "nope"},
        )


def test_interpretation_raw_cannot_also_declare_a_format_hint():
    with pytest.raises(ValidationError):
        FieldSpec(
            number=48, name="bad", data_type="ans", length_type="variable", length_digits=3,
            interpretation=Interpretation.RAW, format_hint="date_mmdd",
        )
