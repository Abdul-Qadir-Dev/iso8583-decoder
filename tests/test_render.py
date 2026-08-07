import pytest
from pydantic import ValidationError

from iso8583_decoder.render import describe_field_error, mask_value
from iso8583_decoder.spec import FieldSpec, MaskStrategy, Sensitivity

PAN = "4111111111111111"
TRACK2 = f"{PAN}=25121019999900000"
TRACK1 = f"B{PAN}^DOE/JOHN^25121000000000"
PIN_BLOCK_HEX = "0102030405060708"  # 8 bytes


def test_pan_masked_by_default(spec):
    result = mask_value(spec.fields[2], PAN)
    assert result == "411111******1111"
    assert PAN not in result


def test_short_pan_falls_back_to_full_mask(spec):
    result = mask_value(spec.fields[2], "12345")
    assert result == "*****"
    assert "1" not in result and "2" not in result


def test_track2_masks_only_the_pan_portion(spec):
    result = mask_value(spec.fields[35], TRACK2)
    assert result == "411111******1111=25121019999900000"
    assert PAN not in result
    assert "25121019999900000" in result  # non-PAN track data is not sensitive here


def test_track1_preserves_format_code_and_name(spec):
    result = mask_value(spec.fields[45], TRACK1)
    assert result == "B411111******1111^DOE/JOHN^25121000000000"
    assert PAN not in result
    assert "DOE/JOHN" in result


def test_unrecognized_track_format_masks_everything(spec):
    raw = "not-a-recognizable-track-blob-but-has-a-pan-like-run-of-1234567890123"
    result = mask_value(spec.fields[35], raw)
    assert result == "*" * len(raw)
    assert "1234567890123" not in result


def test_redacted_pin_block_never_shown(spec):
    result = mask_value(spec.fields[52], PIN_BLOCK_HEX)
    assert result == "[redacted, 8 bytes]"
    assert PIN_BLOCK_HEX not in result


def test_redacted_security_control_info_never_shown(spec):
    result = mask_value(spec.fields[53], PIN_BLOCK_HEX)
    assert result == "[redacted, 8 bytes]"
    assert PIN_BLOCK_HEX not in result


def test_reveal_true_bypasses_masking(spec):
    assert mask_value(spec.fields[2], PAN, reveal=True) == PAN


def test_reveal_defaults_to_off(spec):
    assert mask_value(spec.fields[2], PAN) != PAN


def test_reveal_does_not_bypass_redaction_by_accident_only(spec):
    # redacted fields still respect reveal -- the point is the default is off,
    # not that redaction is unconditional. Confirm the flag actually has to be passed.
    assert mask_value(spec.fields[52], PIN_BLOCK_HEX, reveal=True) == PIN_BLOCK_HEX


def test_non_sensitive_field_passes_through_unchanged(spec):
    result = mask_value(spec.fields[39], "00")
    assert result == "00"


def test_error_message_does_not_leak_raw_pan(spec):
    message = describe_field_error(spec.fields[2], PAN, "length prefix disagreed with actual length")
    assert PAN not in message
    assert "411111******1111" in message


def test_error_message_does_not_leak_track_data(spec):
    message = describe_field_error(spec.fields[35], TRACK2, "unexpected separator")
    assert PAN not in message


def test_error_message_does_not_leak_pin_block(spec):
    message = describe_field_error(spec.fields[52], PIN_BLOCK_HEX, "invalid BCD nibble")
    assert PIN_BLOCK_HEX not in message
    assert "[redacted, 8 bytes]" in message


def test_error_message_respects_explicit_reveal(spec):
    message = describe_field_error(spec.fields[2], PAN, "just checking", reveal=True)
    assert PAN in message


def test_exception_raised_from_field_error_does_not_leak_pan(spec):
    # The failure mode this guards against: a display path masks correctly,
    # then an unrelated error path builds its own exception message straight
    # from the raw value and leaks it. Proving describe_field_error() is safe
    # to raise from is what makes that mistake avoidable in the parser later.
    message = describe_field_error(spec.fields[2], PAN, "example failure")
    exc = ValueError(message)
    assert PAN not in str(exc)


def test_exception_raised_from_field_error_does_not_leak_pin_block(spec):
    message = describe_field_error(spec.fields[52], PIN_BLOCK_HEX, "example failure")
    exc = ValueError(message)
    assert PIN_BLOCK_HEX not in str(exc)


def test_masked_field_requires_mask_strategy():
    with pytest.raises(ValidationError):
        FieldSpec(
            number=2, name="bad", data_type="n", length_type="variable", length_digits=2,
            sensitivity=Sensitivity.MASKED,
        )


def test_mask_strategy_requires_masked_sensitivity():
    with pytest.raises(ValidationError):
        FieldSpec(
            number=2, name="bad", data_type="n", length_type="variable", length_digits=2,
            mask_strategy=MaskStrategy.DIRECT,
        )
