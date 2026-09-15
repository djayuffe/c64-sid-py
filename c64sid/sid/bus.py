from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable, List, Tuple

from ..logger import SystemLogger
from .vic_dma import VicDma


@dataclass
class BusHalfCycle:
    """One PHI2 half-cycle bus observation."""
    cycle: int          # full cycle index
    phi2: int           # 0=low, 1=high
    owner: str          # "CPU" or "VIC"
    addr: int           # 16-bit address (0x0000-0xFFFF) or 0xFFFF for idle/unknown
    rw: int             # 0=read, 1=write, 2=idle
    data: int           # 0-255 (latched value on bus)


class Bus:
    """
    C64 system bus with:
      - per-cycle timing (with PHI2 half-cycles)
      - BA/RDY style stalls (VIC steals cycles)
      - open-bus / floating bus latch

    NOTE: This is still an *emulation* of the bus; it aims to be deterministic and
    provides correct sequencing of read-before-write and RMW phases as observed by
    I/O chips (CIA/VIC/SID). It is not a full transistor-level VIC-II fetch model.
    """

    def __init__(self, system, memory, record_halfcycles: bool = False):
        self.system = system
        self.mem = memory
        self.record_halfcycles = record_halfcycles
        self.halfcycles: List[BusHalfCycle] = []
        self.last_value: int = 0xFF  # open bus latch
        self._cycle: int = 0

    def reset(self) -> None:
        """Reset bus timeline + open-bus latch.

        This is called on C64System.reset() so SID-PRO traces start at cycle 0.
        """
        self.halfcycles.clear()
        self.last_value = 0xFF
        self._cycle = 0


    @property
    def cycle(self) -> int:
        return self._cycle

    def _log_half(self, owner: str, addr: int, rw: int, data: int, phi2: int) -> None:
        if not self.record_halfcycles:
            return
        self.halfcycles.append(BusHalfCycle(
            cycle=self._cycle, phi2=phi2, owner=owner,
            addr=addr & 0xFFFF, rw=rw, data=data & 0xFF
        ))

    def _advance_peripherals_1(self) -> None:
        # Advance chips by one master clock (CPU cycle granularity in this emulator)
        # SID update uses CPU cycles; keep 1:1 with global cycle.
        # Also decay open-bus persistence (floating-bus) at the same cadence.
        try:
            self.mem.decay_bus(1)
        except Exception:
            pass
        for s in self.system.sids:
            s.update(1)
        self.mem.cia1.step(1)
        self.mem.cia2.step(1)
        self.mem.vic.step(1)

        # Update IRQ edges (simplified)
        self.system._poll_irqs()

    def _vic_stall_cycle(self) -> None:
        # VIC owns the bus; CPU is stalled (BA low).
        # We don't model VIC fetch addresses here; we keep address as 0xFFFF (unknown)
        # and keep last_value unchanged unless VIC explicitly drives it.
        self._log_half("VIC", 0xFFFF, 2, self.last_value, 0)
        self._log_half("VIC", 0xFFFF, 2, self.last_value, 1)
        self._advance_peripherals_1()
        self._cycle += 1
        self.system.stats.cpuCycles = self._cycle

    def _wait_ready(self) -> None:
        # Stall while VIC steals the bus (BA low)
        while VicDma.ba_low(self.mem.vic):
            self._vic_stall_cycle()

        # RDY low stretches CPU cycles (best-effort)
        while not bool(getattr(self.system, 'rdyLine', True)):
            self._log_half("CPU", 0xFFFF, 2, self.last_value, 0)
            self._log_half("CPU", 0xFFFF, 2, self.last_value, 1)
            try:
                self.mem._touch_bus(self.last_value)
            except Exception:
                pass
            self._advance_peripherals_1()
            self._cycle += 1
            self.system.stats.cpuCycles = self._cycle

    def idle_cpu_cycle(self, addr_hint: Optional[int] = None) -> None:
        """Consume one CPU cycle with no architecturally-visible action.
        We still allow BA stalls and update open-bus latch deterministically."""
        self._wait_ready()
        self.system.cpu.current_bus_cycle = self._cycle
        addr = 0xFFFF if addr_hint is None else (addr_hint & 0xFFFF)
        # PHI2 low: address stable
        self._log_half("CPU", addr, 2, self.last_value, 0)
        # PHI2 high: "open bus" value stays latched
        self._log_half("CPU", addr, 2, self.last_value, 1)
        try:
            self.mem._touch_bus(self.last_value)
        except Exception:
            pass
        self._advance_peripherals_1()
        self._cycle += 1
        self.system.stats.cpuCycles = self._cycle

    def read(self, addr: int) -> int:
        """One full CPU read cycle, with BA stalls and open-bus latch updates."""
        self._wait_ready()
        self.system.cpu.current_bus_cycle = self._cycle
        a = addr & 0xFFFF
        # PHI2 low: address driven
        self._log_half("CPU", a, 0, self.last_value, 0)

        # Read happens during PHI2 high (conceptually)
        val = self.mem.read(a)
        self.last_value = val & 0xFF
        try:
            self.mem._touch_bus(self.last_value)
        except Exception:
            pass
        self._log_half("CPU", a, 0, self.last_value, 1)

        self._advance_peripherals_1()
        self._cycle += 1
        self.system.stats.cpuCycles = self._cycle
        return self.last_value

    def write(self, addr: int, val: int) -> None:
        """One full CPU write cycle."""
        self._wait_ready()
        self.system.cpu.current_bus_cycle = self._cycle
        a = addr & 0xFFFF
        v = val & 0xFF

        # PHI2 low: address driven
        self._log_half("CPU", a, 1, self.last_value, 0)

        # PHI2 high: data driven by CPU
        self.mem.write(a, v)
        self.last_value = v
        try:
            self.mem._touch_bus(self.last_value)
        except Exception:
            pass
        self._log_half("CPU", a, 1, self.last_value, 1)

        self._advance_peripherals_1()
        self._cycle += 1
        self.system.stats.cpuCycles = self._cycle
