"""Cycle-indexed byte trace helpers for forensic diagnostics."""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass, field


@dataclass
class TraceBuffers:
    """Packed trace buffers: one uint32 cycle and one byte per observation."""
    cycles_u32le: bytearray = field(default_factory=bytearray)
    data_u8: bytearray = field(default_factory=bytearray)


class SidTraceRecorder:
    """Record a cycle-indexed byte stream for deterministic diagnostics.

    This is intentionally a standalone recorder: it does not claim PHI2-level
    bus accuracy and can be attached by callers that need a compact trace.
    """

    def __init__(self) -> None:
        self._cycle = 0
        self._buffers = TraceBuffers()

    @property
    def cycle(self) -> int:
        return self._cycle

    def set_cycle(self, cycle: int) -> None:
        self._cycle = max(0, int(cycle))

    def tick(self, bus_byte: int) -> None:
        self._buffers.cycles_u32le.extend(struct.pack('<I', self._cycle & 0xFFFFFFFF))
        self._buffers.data_u8.append(int(bus_byte) & 0xFF)
        self._cycle += 1

    def tick_idle(self, count: int, bus_byte: int = 0xFF) -> None:
        for _ in range(max(0, int(count))):
            self.tick(bus_byte)

    def snapshot(self) -> tuple[bytes, bytes]:
        return bytes(self._buffers.cycles_u32le), bytes(self._buffers.data_u8)


def b64encode_bytes(data: bytes, chunk_size: int = 256 * 1024) -> str:
    """Encode a byte stream as one valid Base64 value.

    ``chunk_size`` is retained for compatibility with the reference helper;
    Base64's three-byte groups mean arbitrary source chunks cannot safely be
    encoded independently.
    """
    if chunk_size <= 0:
        raise ValueError('chunk_size must be positive')
    return base64.b64encode(data).decode('ascii')
