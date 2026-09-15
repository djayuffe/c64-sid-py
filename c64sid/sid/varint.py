"""Variable-length integer encoding for SID-PRO binary format."""
from __future__ import annotations


def encode_varint(value: int) -> bytes:
    """Encode unsigned integer as variable-length bytes.

    Uses continuation bit encoding:
    - Bit 7: continuation (1 = more bytes follow)
    - Bits 0-6: value bits
    """
    if value < 0:
        raise ValueError(f"VarInt requires non-negative integer, got {value}")

    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode variable-length integer from bytes.

    Returns:
        (value, bytes_consumed)
    """
    value = 0
    shift = 0
    pos = offset

    while pos < len(data):
        byte = data[pos]
        value |= (byte & 0x7F) << shift
        pos += 1

        if not (byte & 0x80):
            return value, pos - offset

        shift += 7
        if shift > 63:
            raise ValueError("VarInt too large (>64 bits)")

    raise ValueError("Incomplete VarInt at end of data")


def encode_varint_signed(value: int) -> bytes:
    """Encode signed integer using zigzag encoding + varint."""
    # ZigZag: 0 -> 0, -1 -> 1, 1 -> 2, -2 -> 3, 2 -> 4, ...
    zigzag = (value << 1) ^ (value >> 63) if value < 0 else (value << 1)
    return encode_varint(zigzag)


def decode_varint_signed(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode signed varint using zigzag decoding."""
    zigzag, consumed = decode_varint(data, offset)
    # Reverse zigzag
    value = (zigzag >> 1) ^ (-(zigzag & 1))
    return value, consumed
