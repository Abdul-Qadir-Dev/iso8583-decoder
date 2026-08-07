def bitmap_hex(present_fields: set[int], base_field: int) -> str:
    """Build 16 hex chars (64 bits) with the given field numbers set, via plain
    integer bit-shifting -- deliberately not the nibble-walking approach
    bitmap.py itself uses, so tests using this check something rather than
    mirroring the implementation."""
    value = 0
    for f in present_fields:
        bit_index_from_msb = f - base_field
        value |= 1 << (63 - bit_index_from_msb)
    return format(value, "016x")
