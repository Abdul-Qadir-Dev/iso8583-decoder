from iso8583_decoder.bitmap import parse_bitmap
from tests.hex_helpers import bitmap_hex as _bitmap_hex


def test_primary_only_no_secondary_indicated():
    primary = _bitmap_hex({2, 39}, base_field=1)
    result = parse_bitmap(primary + "REST-OF-MESSAGE", known_fields={2, 39})
    assert result.present_fields == [2, 39]
    assert result.primary_hex == primary
    assert result.secondary_hex is None
    assert result.consumed_chars == 16
    assert result.partial is False
    assert result.diagnostics == []


def test_secondary_bitmap_present():
    primary = _bitmap_hex({1, 2}, base_field=1)     # bit 1 set -> secondary follows
    secondary = _bitmap_hex({70}, base_field=65)
    result = parse_bitmap(primary + secondary + "REST", known_fields={2, 70})
    assert result.present_fields == [2, 70]
    assert result.secondary_hex == secondary
    assert result.consumed_chars == 32
    assert result.partial is False
    assert result.diagnostics == []


def test_bit1_set_but_secondary_entirely_absent_stops_parsing():
    primary = _bitmap_hex({1, 2}, base_field=1)
    result = parse_bitmap(primary, known_fields={2})  # nothing after the primary bitmap at all
    assert result.partial is True
    assert "doesn't contain one" in result.partial_reason
    assert result.present_fields == [2]  # primary was still read successfully
    assert result.consumed_chars == 16
    stop_diag = next(d for d in result.diagnostics if d.code == "bitmap_secondary_missing")
    assert stop_diag.byte_offset == 16  # where the secondary block was expected to start


def test_bit1_set_but_secondary_truncated_stops_parsing():
    primary = _bitmap_hex({1, 2}, base_field=1)
    result = parse_bitmap(primary + "ABC", known_fields={2})  # only 3 chars follow, not 16
    assert result.partial is True
    assert result.present_fields == [2]
    assert result.consumed_chars == 16


def test_bit65_tertiary_indicator_flags_but_does_not_stop():
    primary = _bitmap_hex({1, 2}, base_field=1)
    secondary = _bitmap_hex({65}, base_field=65)
    result = parse_bitmap(primary + secondary, known_fields={2})
    assert result.partial is False
    assert result.present_fields == [2]  # bit 65 is a control bit, not a data field
    tertiary = next(d for d in result.diagnostics if d.code == "bitmap_tertiary_bit_set")
    assert tertiary.field_number == 65
    assert tertiary.byte_offset == 16  # start of the secondary block, local to this input


def test_unknown_field_in_bitmap_is_diagnostic_not_exception():
    primary = _bitmap_hex({60}, base_field=1)
    result = parse_bitmap(primary, known_fields=set())  # spec doesn't define field 60
    assert result.partial is False
    assert result.present_fields == [60]
    unknown = next(d for d in result.diagnostics if d.code == "bitmap_field_not_in_spec")
    assert unknown.field_number == 60
    assert unknown.byte_offset == 14  # (60-1)//4, local hex-char index within `remaining`


def test_non_hex_primary_stops_parsing():
    result = parse_bitmap("ZZZZZZZZZZZZZZZZ" + "REST", known_fields=set())
    assert result.partial is True
    assert "non-hex" in result.partial_reason
    assert result.present_fields == []
    assert result.consumed_chars == 0


def test_non_hex_secondary_stops_parsing():
    primary = _bitmap_hex({1, 2}, base_field=1)
    result = parse_bitmap(primary + "ZZZZZZZZZZZZZZZZ" + "REST", known_fields={2})
    assert result.partial is True
    assert "non-hex" in result.partial_reason
    assert result.present_fields == [2]  # primary still trustworthy
    assert result.secondary_hex == "ZZZZZZZZZZZZZZZZ"
    assert result.consumed_chars == 16


def test_message_too_short_for_primary_bitmap_stops_parsing():
    result = parse_bitmap("1234", known_fields=set())
    assert result.partial is True
    assert "too short" in result.partial_reason
    assert result.present_fields == []
    assert result.consumed_chars == 0
    assert result.diagnostics[-1].byte_offset == 0


def test_raw_hex_preserved_verbatim_for_display():
    primary = "A1B2C3D4E5F60708"
    result = parse_bitmap(primary, known_fields=set())
    assert result.primary_hex == primary  # case preserved, not normalized
