from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..logger import SystemLogger
from .constants import MAX_CALL_CYCLES, IRQ_VECTOR, NMI_VECTOR
from .cpu6502 import Cpu6502
from .machine_timing import MachineTiming, MachineModel
from .memory_bank import MemoryBank
from .sid_chip import SidChip
from .sid_types import C64Config, InterruptEvent
from .vic_dma import VicDma
from .bus import Bus


def _u16(v: int) -> int:
    return v & 0xFFFF


@dataclass
class C64SystemStats:
    cpuCycles: int = 0
    instructions: int = 0


class C64System:
    def __init__(self, cfg: Optional[C64Config] = None):
        self.cfg = cfg or C64Config()
        self.memory = MemoryBank(self.cfg)
        self.cpu = Cpu6502(self.memory.read, self.memory.write)

        # Bus: per-cycle timeline with BA stalls + optional PHI2 half-cycle trace
        self.bus = Bus(self, self.memory, record_halfcycles=bool(getattr(cfg, 'recordHalfCycles', False)))
        # Route CPU memory cycles through bus (enables BA stalls + open bus + RMW phases)
        self.cpu.read_fn = self.bus.read
        self.cpu.write_fn = self.bus.write
        self.cpu.idle_fn = self.bus.idle_cpu_cycle
        # Single source of truth for time (cycle-accurate traces + stalls)
        self.cpu.cycle_fn = lambda: self.bus.cycle

        # IRQ edge tracking
        self._prev_vic_irq = False
        self._prev_cia1_irq = False
        self._prev_cia2_irq = False
        # RDY line (external stretch). True=ready
        self.rdyLine = True

        self.model: MachineModel = MachineTiming.PAL
        self.sid: Optional[SidChip] = None
        self.sids: List[SidChip] = []
        self.stats = C64SystemStats()
        self._pending_irqs: List[InterruptEvent] = []

    def set_model(self, ntsc: bool) -> None:
        self.model = MachineTiming.get(ntsc)
        self.memory.vic.set_standard(ntsc)
        # Keep CIA TOD derivation consistent with machine clock.
        try:
            self.memory.cia1.clock_hz = int(self.model.clockHz)
            self.memory.cia2.clock_hz = int(self.model.clockHz)
        except Exception:
            pass

    def attach_sid(self, sid: SidChip, base: int = 0xD400) -> None:
        self.attach_sids([sid], [base])

    def attach_sids(self, sids: List[SidChip], bases: List[int]) -> None:
        self.sids = sids
        self.sid = sids[0] if sids else None
        self.memory.install_sids(sids, bases)

    def load_program(self, addr: int, data: bytes) -> None:
        self.memory.load(addr, data)

    def reset(self) -> None:
        self.stats = C64SystemStats()
        self._pending_irqs.clear()
        self._prev_vic_irq = False
        self._prev_cia1_irq = False
        self._prev_cia2_irq = False
        self.memory.reset()
        try:
            self.bus.reset()
        except Exception:
            pass
        self.cpu.reset()

    def _poll_irqs(self) -> None:
        """Edge-detect IRQ sources and queue interrupt events."""
        vic_irq = bool(self.memory.vic.irqLine)
        if vic_irq and not self._prev_vic_irq:
            self.queue_interrupt('IRQ', source='VIC-II')
        self._prev_vic_irq = vic_irq

        cia1_irq = bool(self.memory.cia1.irqLine)
        if cia1_irq and not self._prev_cia1_irq:
            self.queue_interrupt('IRQ', source='CIA1')
        self._prev_cia1_irq = cia1_irq

        cia2_irq = bool(self.memory.cia2.irqLine)
        if cia2_irq and not self._prev_cia2_irq:
            # CIA2 drives the 6510 NMI line on a C64.
            self.queue_interrupt('NMI', source='CIA2')
        self._prev_cia2_irq = cia2_irq

    def queue_interrupt(self, evt: InterruptEvent | str, *, source: str = 'external') -> None:
        """Queue an interrupt event.

        Accepting a type string keeps peripheral edge detection concise while
        retaining the structured event API for external callers.
        """
        if isinstance(evt, str):
            if evt not in ('IRQ', 'NMI'):
                raise ValueError(f'Unknown interrupt type: {evt}')
            vector = NMI_VECTOR if evt == 'NMI' else IRQ_VECTOR
            handler = self.memory.peek(vector) | (self.memory.peek(vector + 1) << 8)
            evt = InterruptEvent(cycles=self.bus.cycle, type=evt, source=source,
                                 vectorAddr=vector, handlerAddr=handler)
        self._pending_irqs.append(evt)

    def _service_interrupts(self) -> int:
        extra = 0
        # NMI has priority over IRQ - only one serviced per instruction boundary

        # Service NMI first
        for evt in self._pending_irqs[:]:  # Iterate over a copy
            if evt.type == 'NMI':
                self._pending_irqs.remove(evt)
                SystemLogger.log('C64', f'NMI from {evt.source}: handler=${evt.handlerAddr:04X}', 'debug')
                extra += self.cpu.nmi()
                return extra

        # Then service IRQ
        for evt in self._pending_irqs[:]:  # Iterate over a copy
            if evt.type == 'IRQ':
                self._pending_irqs.remove(evt)
                SystemLogger.log('C64', f'IRQ from {evt.source}: handler=${evt.handlerAddr:04X}', 'debug')
                extra += self.cpu.irq()
                return extra

        return extra

    def step(self, max_cycles: int) -> int:
        """Run the machine for max_cycles CPU cycles.

        Timing is driven by the Bus, so VIC BA stalls are represented by additional cycles.
        """
        start = self.bus.cycle
        target = start + int(max_cycles)

        while self.bus.cycle < target:
            self._service_interrupts()
            self.cpu.step()
            self.stats.instructions += 1

        return self.bus.cycle - start

    def call(self, addr: int, max_cycles: int = 200000, a: int | None = None, x: int | None = None, y: int | None = None) -> int:
        """Call a subroutine and run until it returns, bounded by ``max_cycles``.

        Optional a/x/y let callers set registers before the call (common for SID init/play).
        """
        SystemLogger.log('C64', f'Calling routine at ${addr:04X}', 'debug')
        if a is not None:
            self.cpu.a = int(a) & 0xFF
        if x is not None:
            self.cpu.x = int(x) & 0xFF
        if y is not None:
            self.cpu.y = int(y) & 0xFF
        budget = min(max(0, int(max_cycles)), MAX_CALL_CYCLES)
        return_pc = self.cpu.pc
        start = self.bus.cycle
        self.cpu.hle_jsr(addr)
        while self.bus.cycle - start < budget:
            self._service_interrupts()
            self.cpu.step()
            self.stats.instructions += 1
            if self.cpu.pc == return_pc:
                return self.bus.cycle - start
        raise TimeoutError(f'Routine at ${addr:04X} did not return within {budget} cycles')

    def run_for_frames(self, frames: int) -> None:
        for _ in range(max(0, int(frames))):
            self.step(self.model.cyclesPerFrame)
