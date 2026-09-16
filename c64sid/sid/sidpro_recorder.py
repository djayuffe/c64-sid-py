from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SidProBusEvent:
    """A single SID register write event."""

    cycle: float
    chip: int
    reg: int
    value: int


class SidProRecorder:
    """Low-overhead collector for SID-PRO bus events.

    Stores:
      - cycles: List[float]   (absolute C64 CPU cycle index)
      - events: bytearray    (triples: chip_index, register, value)
    """

    __slots__ = ("cycles", "events")

    def __init__(self) -> None:
        self.cycles: List[float] = []
        self.events = bytearray()

    def reset(self) -> None:
        self.cycles.clear()
        self.events.clear()

    def record(self, cycle: float, chip_index: int, register: int, value: int) -> None:
        # Keep format strictly within 0..255 for event bytes
        c = float(cycle)
        self.cycles.append(c)
        self.events.append(chip_index & 0xFF)
        self.events.append(register & 0xFF)
        self.events.append(value & 0xFF)

    def count(self) -> int:
        return len(self.cycles)

    def assert_consistent(self) -> None:
        if len(self.events) != len(self.cycles) * 3:
            raise ValueError(
                f"SID-PRO recorder internal mismatch: cycles={len(self.cycles)} events_bytes={len(self.events)}"
            )
class IoProRecorder:
    """Recorder for generic I/O writes (for 1:1 forensic replay).

    Records events as:
      - cycles: List[float]  (float64 timestamps per write)
      - events: bytearray    (records: addr_lo, addr_hi, value)
    """

    __slots__ = ("cycles", "events")

    def __init__(self) -> None:
        self.cycles: List[float] = []
        self.events = bytearray()

    def reset(self) -> None:
        self.cycles.clear()
        self.events.clear()

    def record(self, cycle: float, addr: int, value: int) -> None:
        c = float(cycle)
        a = int(addr) & 0xFFFF
        v = int(value) & 0xFF
        self.cycles.append(c)
        self.events.append(a & 0xFF)
        self.events.append((a >> 8) & 0xFF)
        self.events.append(v)

    def count(self) -> int:
        return len(self.cycles)

    def assert_consistent(self) -> None:
        if len(self.events) != len(self.cycles) * 3:
            raise ValueError(
                f"IO recorder internal mismatch: cycles={len(self.cycles)} events_bytes={len(self.events)}"
            )
