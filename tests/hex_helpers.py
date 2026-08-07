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


def pack_bcd(digits: str, pad_leading: bool = True, pad_nibble: int = 0xF) -> str:
    """Hex-dump representation of `digits` BCD-packed two-per-byte, built by
    string concatenation rather than binary_extract.py's nibble-list/int
    approach, so a test using this checks something instead of mirroring
    the implementation. A decimal digit character is already a valid hex
    character, so once the length is padded to even, pairing characters up
    two at a time directly gives valid hex byte pairs -- no arithmetic needed."""
    if len(digits) % 2 == 1:
        pad_char = format(pad_nibble, "x")
        digits = pad_char + digits if pad_leading else digits + pad_char
    return digits


def ascii_hex(text: str) -> str:
    """Hex-dump representation of `text` as raw ASCII bytes."""
    return text.encode("ascii").hex()
