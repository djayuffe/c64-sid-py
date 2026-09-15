from __future__ import annotations

from typing import List, Optional

from ..logger import SystemLogger
from .constants import BASIC_ROM_SIZE, KERNAL_ROM_SIZE, CHARGEN_ROM_SIZE
from .sid_chip import SidChip
from .cia6526 import Cia6526
from .vic_ii import VicII
from .sid_types import C64Config


def _u8(v: int) -> int:
    return v & 0xFF


def _u16(v: int) -> int:
    return v & 0xFFFF


class MemoryBank:
    """C64 memory map + I/O routing.

    Port of TS MemoryBank with fixes:
    - Correct open-bus/value persistence
    - SID read signature mismatch fixed
    """

    def __init__(self, cfg: Optional[C64Config] = None):
        self.cfg = cfg or C64Config()
        self.ram = bytearray(65536)
        self.basic: Optional[bytes] = None
        self.kernal: Optional[bytes] = None
        self.chargen: Optional[bytes] = None

        self.ioEnabled = True
        self.basicEnabled = True
        self.kernalEnabled = True
        self.chargenEnabled = False

        # 6510 CPU port ($0000 DDR, $0001 DATA)
        # Real C64 power-on defaults: DDR=$2F, DATA=$37.
        self.cpu_port_ddr = 0x2F
        self.cpu_port_data = 0x37
        # External lines (inputs when DDR bit=0). Unwired bits float high.
        # (Tape/IEC/LED/motor are not modeled here; callers may override.)
        self.cpu_port_external = 0xFF

        self.lastBusValue = 0
        self.busHold = 0
        self.busHoldDecay = int(self.cfg.busPersistenceCycles)

        self.sids: List[SidChip] = []
        self.sidBases: List[int] = []

        # SID-PRO forensic capture (optional). The recorder interface is:
        #   record(cycle: float, chip_index: int, register: int, value: int) -> None
        # The cycle provider returns the *exact* cycle number for the current bus access.
        self._sidpro_recorder = None
        self._sidpro_cycle_provider = None

        # Optional I/O capture (CIA/VIC/$0000-$0001/etc.)
        #   record(cycle: float, addr: int, value: int) -> None
        self._iopro_recorder = None
        self._iopro_cycle_provider = None

        # Peripherals
        self.cia1 = Cia6526('CIA1')
        self.cia2 = Cia6526('CIA2')
        self.vic = VicII()

    def install_sidpro(self, recorder, cycle_provider) -> None:
        """Attach a SID-PRO recorder.

        recorder: object with .record(cycle, chip_index, register, value)
        cycle_provider: callable returning a numeric cycle for the current bus access
        """
        self._sidpro_recorder = recorder
        self._sidpro_cycle_provider = cycle_provider

    def uninstall_sidpro(self) -> None:
        self._sidpro_recorder = None
        self._sidpro_cycle_provider = None

    def install_iopro(self, recorder, cycle_provider) -> None:
        """Attach an I/O recorder.

        recorder: object with .record(cycle, addr, value)
        cycle_provider: callable returning the current bus cycle for this access
        """
        self._iopro_recorder = recorder
        self._iopro_cycle_provider = cycle_provider

    def uninstall_iopro(self) -> None:
        self._iopro_recorder = None
        self._iopro_cycle_provider = None



    def reset(self) -> None:
        for i in range(len(self.ram)):
            self.ram[i] = 0
        self.lastBusValue = 0
        self.busHold = 0

        # Reset CPU port to power-on values
        self.cpu_port_ddr = 0x2F
        self.cpu_port_data = 0x37
        self.cpu_port_external = 0xFF
        # Keep RAM image coherent with port regs
        self.ram[0x0000] = self.cpu_port_ddr
        self.ram[0x0001] = self.cpu_port_data

        self._update_banking_from_cpu_port()
        self.cia1.reset()
        self.cia2.reset()
        self.vic.reset()
        for sid in self.sids:
            sid.reset()

    def install_roms(self, basic: Optional[bytes], kernal: Optional[bytes], chargen: Optional[bytes]) -> None:
        if basic is not None and len(basic) != BASIC_ROM_SIZE:
            SystemLogger.log('Memory', f'Warning: BASIC ROM should be {BASIC_ROM_SIZE} bytes, got {len(basic)}', 'warn')
        if kernal is not None and len(kernal) != KERNAL_ROM_SIZE:
            SystemLogger.log('Memory', f'Warning: KERNAL ROM should be {KERNAL_ROM_SIZE} bytes, got {len(kernal)}', 'warn')
        if chargen is not None and len(chargen) != CHARGEN_ROM_SIZE:
            SystemLogger.log('Memory', f'Warning: CHARGEN ROM should be {CHARGEN_ROM_SIZE} bytes, got {len(chargen)}', 'warn')

        self.basic = basic
        self.kernal = kernal
        self.chargen = chargen

    def install_sids(self, sids: List[SidChip], bases: List[int]) -> None:
        self.sids = sids
        self.sidBases = bases

    def poke(self, addr: int, val: int) -> None:
        self.write(addr, val)

    def peek(self, addr: int) -> int:
        """Side-effect free read for debug/introspection.

        IMPORTANT: This intentionally does *not* touch the open-bus latch and does
        not perform I/O side effects. It's meant for opcode peeking and analysis.
        """
        a = _u16(addr)

        # ROM windows (no bus touch)
        if 0xA000 <= a <= 0xBFFF and self.basicEnabled and self.basic is not None:
            return self.basic[a - 0xA000]
        if 0xE000 <= a <= 0xFFFF and self.kernalEnabled and self.kernal is not None:
            return self.kernal[a - 0xE000]

        # Everything else: raw RAM image (including I/O mirrors)
        return self.ram[a]

    def _cpu_port_effective(self) -> int:
        """Return the effective value on the 6510 port pins.

        For each bit: if DDR=1 -> driven by DATA; else -> external (defaults high).
        """
        ddr = self.cpu_port_ddr & 0xFF
        data = self.cpu_port_data & 0xFF
        ext = self.cpu_port_external & 0xFF
        return (data & ddr) | (ext & (~ddr & 0xFF))

    def _update_banking_from_cpu_port(self) -> None:
        """Update ROM/I/O banking from 6510 port effective pins.

        Banking pins are LORAM (bit0), HIRAM (bit1), CHAREN (bit2).
        """
        p = self._cpu_port_effective() & 0x07

        loram = (p & 0x01) != 0
        hiram = (p & 0x02) != 0
        charen = (p & 0x04) != 0

        # I/O is visible when CHAREN=1
        self.ioEnabled = bool(charen)
        # BASIC visible when LORAM=1 and HIRAM=1
        self.basicEnabled = bool(loram and hiram)
        # KERNAL visible when HIRAM=1
        self.kernalEnabled = bool(hiram)
        # CHARGEN visible when I/O is disabled and HIRAM=1 (common mapping)
        self.chargenEnabled = (not self.ioEnabled) and bool(hiram)

    def decay_bus(self, cycles: int) -> None:
        if self.busHoldDecay <= 0:
            return
        self.busHold = max(0, self.busHold - max(0, int(cycles)))

    def _touch_bus(self, val: int) -> None:
        self.lastBusValue = _u8(val)
        self.busHold = self.busHoldDecay

    def _open_bus(self) -> int:
        if self.busHoldDecay <= 0:
            return self.lastBusValue
        return self.lastBusValue if self.busHold > 0 else 0xFF

    def read(self, addr: int) -> int:
        a = _u16(addr)

        # 6510 CPU port registers ($0000 DDR, $0001 DATA) have special read semantics.
        if a == 0x0000:
            val = self.cpu_port_ddr & 0xFF
            self._touch_bus(val)
            return val
        if a == 0x0001:
            # Readback is DDR-masked: outputs read as data, inputs read as external.
            val = self._cpu_port_effective() & 0xFF
            self._touch_bus(val)
            return val

        # RAM or ROM
        if 0xA000 <= a <= 0xBFFF and self.basicEnabled and self.basic is not None:
            val = self.basic[a - 0xA000]
            self._touch_bus(val)
            return val

        if 0xE000 <= a <= 0xFFFF and self.kernalEnabled and self.kernal is not None:
            val = self.kernal[a - 0xE000]
            self._touch_bus(val)
            return val

        # I/O / chargen
        if 0xD000 <= a <= 0xDFFF:
            if self.ioEnabled:
                # SID(s)
                for i, base in enumerate(self.sidBases):
                    if a >= base and a <= base + 0x1F:
                        sidReg = a - base
                        val = self.sids[i].read(sidReg, self._open_bus())
                        self._touch_bus(val)
                        return val

                # VIC
                if 0xD000 <= a <= 0xD3FF:
                    val = self.vic.read(a, self._open_bus())
                    self._touch_bus(val)
                    return val

                # CIA1
                if 0xDC00 <= a <= 0xDCFF:
                    val = self.cia1.read(a, self._open_bus())
                    self._touch_bus(val)
                    return val

                # CIA2
                if 0xDD00 <= a <= 0xDDFF:
                    val = self.cia2.read(a, self._open_bus())
                    self._touch_bus(val)
                    return val

                # Unmapped I/O -> open bus
                val = self._open_bus()
                self._touch_bus(val)
                return val

            # chargen when I/O disabled
            if self.chargenEnabled and self.chargen is not None:
                val = self.chargen[a - 0xD000]
                self._touch_bus(val)
                return val

        val = self.ram[a]
        self._touch_bus(val)
        return val

    def write(self, addr: int, val: int) -> None:
        a = _u16(addr)
        v = _u8(val)

        # IO-PRO capture (optional): record key I/O writes for 1:1 replay
        if self._iopro_recorder is not None and self._iopro_cycle_provider is not None:
            try:
                if a in (0x0000, 0x0001) or (0xD000 <= a <= 0xDFFF and self.ioEnabled):
                    cyc = float(self._iopro_cycle_provider())
                    self._iopro_recorder.record(cyc, a, v)
            except Exception:
                pass

        # 6510 CPU port ($0000 DDR, $0001 DATA)
        if a == 0x0000:
            self.cpu_port_ddr = v
            self.ram[0x0000] = v
            self._update_banking_from_cpu_port()
            self._touch_bus(v)
            return

        if a == 0x0001:
            self.cpu_port_data = v
            self.ram[0x0001] = v
            self._update_banking_from_cpu_port()
            self._touch_bus(v)
            return

        # RAM always writable
        self.ram[a] = v

        # I/O writes
        if 0xD000 <= a <= 0xDFFF and self.ioEnabled:
            # SID(s)
            for i, base in enumerate(self.sidBases):
                if a >= base and a <= base + 0x1F:
                    # SID-PRO capture (register writes only: 0x00..0x1C)
                    if self._sidpro_recorder is not None and self._sidpro_cycle_provider is not None:
                        reg = a - base
                        if 0 <= reg <= 0x1C:
                            try:
                                cyc = float(self._sidpro_cycle_provider())
                            except Exception:
                                cyc = 0.0
                            self._sidpro_recorder.record(cyc, i, reg, v)
                    self.sids[i].write(a - base, v)
                    self._touch_bus(v)
                    return

            # VIC
            if 0xD000 <= a <= 0xD3FF:
                self.vic.write(a, v)
                self._touch_bus(v)
                return

            # CIA1
            if 0xDC00 <= a <= 0xDCFF:
                self.cia1.write(a, v)
                self._touch_bus(v)
                return

            # CIA2
            if 0xDD00 <= a <= 0xDDFF:
                self.cia2.write(a, v)
                # VIC bank select is driven by CIA2 Port A bits 0..1 ($DD00).
                # On a real C64, undriven inputs float high, so DDR=0 behaves as '1'.
                reg = a & 0x0F
                if reg in (0x00, 0x02):
                    eff = (self.cia2.pra & self.cia2.ddra) | (0xFF & (~self.cia2.ddra & 0xFF))
                    bank = 3 - (eff & 0x03)
                    self.vic.mem_bank_base = (bank & 0x03) * 0x4000
                self._touch_bus(v)
                return

        self._touch_bus(v)

    def load(self, addr: int, data: bytes) -> None:
        a = _u16(addr)
        end = min(65536, a + len(data))
        self.ram[a:end] = data[: end - a]
        SystemLogger.log('MemoryBank', f'Loaded {end-a} bytes at ${a:04X}', 'debug')
