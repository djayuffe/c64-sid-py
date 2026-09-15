from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .cpu_illegals import CpuIllegals

# --- Bus-cycle exact I/O semantics helpers ---
RMW_OPS = {
    # ASL
    0x06, 0x16, 0x0E, 0x1E,
    # LSR
    0x46, 0x56, 0x4E, 0x5E,
    # ROL
    0x26, 0x36, 0x2E, 0x3E,
    # ROR
    0x66, 0x76, 0x6E, 0x7E,
    # INC
    0xE6, 0xF6, 0xEE, 0xFE,
    # DEC
    0xC6, 0xD6, 0xCE, 0xDE,
    # Common illegal RMWs used in demos (best-effort)
    0x03, 0x13, 0x0F, 0x1F, 0x1B, 0x07, 0x17, 0x0B,
    0x23, 0x33, 0x2F, 0x3F, 0x3B,
    0x43, 0x53, 0x4F, 0x5F, 0x5B,
    0x63, 0x73, 0x6F, 0x7F, 0x7B,
    0xC3, 0xD3, 0xCF, 0xDF, 0xDB, 0xD7,
    0xE3, 0xF3, 0xEF, 0xFF, 0xFB, 0xF7,
}

STORE_DUMMY_READ_OPS = {
    0x9D, 0x99, 0x91,  # STA abs,X / abs,Y / (zp),Y
    0x9C,              # SHY abs,X (best-effort)
    0x9E,              # SHX abs,Y (best-effort)
    0x93, 0x9F,        # AHX (ind),Y / abs,Y (best-effort)
    0x9B,              # TAS abs,Y (best-effort)
}



def _u8(v: int) -> int:
    return v & 0xFF


def _u16(v: int) -> int:
    return v & 0xFFFF


@dataclass
class CpuState:
    a: int
    x: int
    y: int
    sp: int
    pc: int
    flags: int
    cycles: int


class Cpu6502:
    # Flag bits
    C = 0x01
    Z = 0x02
    I = 0x04
    D = 0x08
    B = 0x10
    U = 0x20
    V = 0x40
    N = 0x80

    def __init__(
        self,
        read_fn: Callable[[int], int],
        write_fn: Callable[[int, int], None],
        idle_fn: Optional[Callable[[Optional[int]], None]] = None,
        cycle_fn: Optional[Callable[[], int]] = None,
    ):
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFF
        self.pc = 0
        self.flags = Cpu6502.U | Cpu6502.I
        # Total cycles executed. When a Bus is attached, this is driven by Bus.cycle
        # (including BA/RDY stalls). Otherwise, falls back to instruction-level count.
        self.cycles = 0
        # Back-compat alias used by older capture code.
        self.bus_cycle = 0
        self.current_bus_cycle = 0
        self._instr_base = 0
        self._instr_bus_i = 0
        self.read_fn = read_fn
        self.write_fn = write_fn
        self.idle_fn = idle_fn
        self.cycle_fn = cycle_fn
        self._instr_cycles_done = 0
        self._current_op = 0
        self._rmw_old_write_done = False
        self._last_read_addr: Optional[int] = None
        self._last_read_val = 0xFF
        self._store_dummy_addr: Optional[int] = None
        self._store_dummy_done = False

    def snapshot(self) -> CpuState:
        return CpuState(self.a, self.x, self.y, self.sp, self.pc, self.flags, self.cycles)

    def _now(self) -> int:
        """Return the authoritative global cycle counter.

        When running under :class:`~c64sid.sid.bus.Bus`, this is driven by
        ``Bus.cycle`` (including BA/RDY stalls)."""
        if self.cycle_fn is not None:
            try:
                return int(self.cycle_fn())
            except Exception:
                pass
        return int(self.cycles)

    def _bus_access(self) -> int:
        """Mark a single bus access within the current instruction.

        NOTE: This is not a full NMOS 6502 micro-cycle model, but it provides a
        deterministic, drift-free cycle index for memory-mapped I/O captures.
        """
        self.current_bus_cycle = self._instr_base + self._instr_bus_i
        self._instr_bus_i += 1
        return self.current_bus_cycle

    # --- Memory helpers ---
    def read(self, addr: int) -> int:
        self._instr_cycles_done += 1
        v = _u8(self.read_fn(_u16(addr)))
        self._last_read_addr = _u16(addr)
        self._last_read_val = v
        return v

    def write(self, addr: int, val: int) -> None:
        a = _u16(addr)
        v = _u8(val)

        # Dummy read-before-write phase for indexed stores (I/O-visible).
        if (self._current_op in STORE_DUMMY_READ_OPS) and (not self._store_dummy_done) and (self._store_dummy_addr is not None):
            self._instr_cycles_done += 1
            dv = _u8(self.read_fn(_u16(self._store_dummy_addr)))
            self._last_read_addr = _u16(self._store_dummy_addr)
            self._last_read_val = dv
            self._store_dummy_done = True

        # Exact RMW sequence: read -> write old -> write new.
        if (self._current_op in RMW_OPS) and (not self._rmw_old_write_done) and (self._last_read_addr is not None) and (a == _u16(self._last_read_addr)):
            self._instr_cycles_done += 1
            self.write_fn(a, _u8(self._last_read_val))
            self._rmw_old_write_done = True

        self._instr_cycles_done += 1
        self.write_fn(a, v)

    def idle_cycle(self, addr_hint: Optional[int] = None) -> None:
        """Consume one CPU internal cycle (still bus-visible when a Bus is attached)."""
        if self.idle_fn is not None:
            self.idle_fn(addr_hint)
        self._instr_cycles_done += 1

    def read16(self, addr: int) -> int:
        lo = self.read(addr)
        hi = self.read(addr + 1)
        return (hi << 8) | lo

    def read16bug(self, addr: int) -> int:
        lo = self.read(addr)
        hi_addr = (addr & 0xFF00) | ((addr + 1) & 0x00FF)
        hi = self.read(hi_addr)
        return (hi << 8) | lo

    # --- Stack ---
    def push(self, v: int) -> None:
        self.write(0x0100 | self.sp, v)
        self.sp = _u8(self.sp - 1)

    def pull(self) -> int:
        self.sp = _u8(self.sp + 1)
        return self.read(0x0100 | self.sp)

    # --- Flags ---
    def get_flag(self, m: int) -> bool:
        return (self.flags & m) != 0

    def set_flag(self, m: int, on: bool) -> None:
        if on:
            self.flags |= m
        else:
            self.flags &= ~m

    def set_zn(self, v: int) -> None:
        v = _u8(v)
        self.set_flag(Cpu6502.Z, v == 0)
        self.set_flag(Cpu6502.N, (v & 0x80) != 0)

    # --- Reset/IRQ/NMI ---
    def reset(self, vector: int = 0xFFFC) -> None:
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFD
        self.flags = Cpu6502.U | Cpu6502.I
        start = self._now()
        self._instr_base = start
        self._instr_bus_i = 0
        self.bus_cycle = start

        # Reset sequence is 7 cycles on NMOS 6510. We model the 5 internal
        # cycles as bus-visible idles, followed by vector fetch.
        for _ in range(5):
            self.idle_cycle(self.pc)
        lo = self.read(vector)
        hi = self.read(vector + 1)
        self.pc = ((hi << 8) | lo) & 0xFFFF

        end = self._now()
        self.cycles = end
        self.bus_cycle = end

    def irq_vector(self, vector: int, brk: bool = False) -> int:
        # Treat IRQ/NMI as a 7-cycle sequence on the bus.
        start = self._now()
        self._instr_base = start
        self._instr_bus_i = 0
        self.bus_cycle = start

        # 1) dummy read of next opcode byte (I/O-visible)
        self.read(self.pc)
        # 2-4) push PC and P
        self.push((self.pc >> 8) & 0xFF)
        self.push(self.pc & 0xFF)
        flags = self.flags | Cpu6502.U
        if brk:
            flags |= Cpu6502.B
        else:
            flags &= ~Cpu6502.B
        self.push(flags)
        # 5) internal cycle (best-effort)
        self.idle_cycle(self.pc)
        self.set_flag(Cpu6502.I, True)
        # NMOS 6502/6510: D flag cleared on IRQ/NMI (not on BRK)
        if not brk:
            self.set_flag(Cpu6502.D, False)
        # 6-7) vector fetch
        lo = self.read(vector)
        hi = self.read(vector + 1)
        self.pc = ((hi << 8) | lo) & 0xFFFF

        end = self._now()
        self.cycles = end
        self.bus_cycle = end
        return end - start

    def irq(self) -> int:
        if self.get_flag(Cpu6502.I):
            return 0
        return self.irq_vector(0xFFFE, False)

    def nmi(self) -> int:
        return self.irq_vector(0xFFFA, False)

    def hle_jsr(self, addr: int) -> int:
        """High-level JSR helper used by the RSID bootstrap/call() path.

        We intentionally avoid polluting the bus with operand reads, but we still
        keep the *cycle-accurate* timeline by consuming the canonical 6 cycles.
        """
        start = self._now()
        self._instr_base = start
        self._instr_bus_i = 0
        self.bus_cycle = start

        # JSR is 6 cycles total; two are the stack writes. We model the remaining
        # four as idles.
        for _ in range(4):
            self.idle_cycle(self.pc)

        ret = _u16(self.pc - 1)
        self.push((ret >> 8) & 0xFF)
        self.push(ret & 0xFF)
        self.pc = _u16(addr)

        end = self._now()
        self.cycles = end
        self.bus_cycle = end
        return end - start

    # --- ALU ---
    def adc(self, v: int) -> None:
        v &= 0xFF
        a = self.a & 0xFF
        c = 1 if self.get_flag(Cpu6502.C) else 0

        if self.get_flag(Cpu6502.D):
            # BCD mode
            lo = (a & 0x0F) + (v & 0x0F) + c
            if lo > 0x09:
                lo += 0x06
            hi = (a >> 4) + (v >> 4) + (1 if lo > 0x0F else 0)
            if hi > 0x09:
                hi += 0x06
            res = ((hi & 0x0F) << 4) | (lo & 0x0F)
            self.set_flag(Cpu6502.C, hi > 0x0F)
            # V flag behavior in BCD is undefined, use binary calculation
            r = a + v + c
            self.set_flag(Cpu6502.V, (~(a ^ v) & (a ^ (r & 0xFF)) & 0x80) != 0)
            self.a = res & 0xFF
            self.set_zn(self.a)
        else:
            # Binary mode
            r = a + v + c
            res = r & 0xFF
            self.set_flag(Cpu6502.C, r > 0xFF)
            self.set_flag(Cpu6502.V, (~(a ^ v) & (a ^ res) & 0x80) != 0)
            self.a = res
            self.set_zn(self.a)

    def sbc(self, v: int) -> None:
        """NMOS 6502/6510 SBC with correct BCD behavior.

        In decimal mode, SBC is *not* equivalent to ADC(~v).
        """
        a = self.a & 0xFF
        v = v & 0xFF
        c = 1 if self.get_flag(Cpu6502.C) else 0

        if self.get_flag(Cpu6502.D):
            # Binary subtract to derive carry/overflow (BCD V flag is undefined,
            # but real silicon derives it from the binary operation).
            r = a - v - (1 - c)
            res_bin = r & 0xFF
            self.set_flag(Cpu6502.C, r >= 0)  # no borrow
            self.set_flag(Cpu6502.V, ((a ^ res_bin) & (a ^ v) & 0x80) != 0)

            # BCD adjust
            lo = (a & 0x0F) - (v & 0x0F) - (1 - c)
            hi = (a >> 4) - (v >> 4)
            if lo < 0:
                lo -= 6
                hi -= 1
            if hi < 0:
                hi -= 6
            res = ((hi << 4) & 0xF0) | (lo & 0x0F)

            self.a = res & 0xFF
            self.set_zn(self.a)
        else:
            # Binary mode: A - v - (1-C)
            r = a - v - (1 - c)
            res = r & 0xFF
            self.set_flag(Cpu6502.C, r >= 0)
            self.set_flag(Cpu6502.V, ((a ^ res) & (a ^ v) & 0x80) != 0)
            self.a = res
            self.set_zn(self.a)

    def cmp(self, a: int, v: int) -> None:
        a &= 0xFF
        v &= 0xFF
        r = (a - v) & 0x1FF
        self.set_flag(Cpu6502.C, a >= v)
        self.set_zn(r & 0xFF)

    def branch(self, cond: bool) -> int:
        rel = self.fetch()
        if rel & 0x80:
            rel -= 0x100
        if not cond:
            return 2
        old_pc = self.pc
        target = _u16(old_pc + rel)
        # Taken branch costs +1 cycle (dummy read of next opcode).
        self.read(old_pc)
        cyc = 3
        # Page-crossing costs another cycle (dummy read with old high byte).
        if (old_pc & 0xFF00) != (target & 0xFF00):
            self.read((old_pc & 0xFF00) | (target & 0x00FF))
            cyc += 1
        self.pc = target
        return cyc

    # --- Fetch/decode helpers ---
    def fetch(self) -> int:
        v = self.read(self.pc)
        self.pc = _u16(self.pc + 1)
        return v

    # addressing modes
    def _zp(self) -> int:
        return self.fetch()

    def _zpX(self) -> int:
        return _u8(self.fetch() + self.x)

    def _zpY(self) -> int:
        return _u8(self.fetch() + self.y)

    def _abs(self) -> int:
        lo = self.fetch(); hi = self.fetch()
        return (hi << 8) | lo

    def _absX(self) -> Tuple[int, bool]:
        base = self._abs()
        lo = base & 0x00FF
        hi = base & 0xFF00
        addr_nc = _u16(hi | _u8(lo + self.x))
        addr = _u16(base + self.x)
        self._store_dummy_addr = addr_nc
        return addr, (base & 0xFF00) != (addr & 0xFF00)

    def _absY(self) -> Tuple[int, bool]:
        base = self._abs()
        lo = base & 0x00FF
        hi = base & 0xFF00
        addr_nc = _u16(hi | _u8(lo + self.y))
        addr = _u16(base + self.y)
        self._store_dummy_addr = addr_nc
        return addr, (base & 0xFF00) != (addr & 0xFF00)

    def _indX(self) -> int:
        zp = _u8(self.fetch() + self.x)
        return self.read(zp) | (self.read(_u8(zp + 1)) << 8)

    def _indY(self) -> Tuple[int, bool]:
        zp = self.fetch()
        base = self.read(zp) | (self.read(_u8(zp + 1)) << 8)
        lo = base & 0x00FF
        hi = base & 0xFF00
        addr_nc = _u16(hi | _u8(lo + self.y))
        addr = _u16(base + self.y)
        self._store_dummy_addr = addr_nc
        return addr, (base & 0xFF00) != (addr & 0xFF00)

    # --- Bus-dummy-read helpers (NMOS 6510 semantics) ---
    # For *reads*, page-crossing adds a cycle that is a *dummy read* of the
    # non-carried address (I/O-visible). For *RMW* abs,X and illegal RMWs, there
    # is always an index-add dummy read.
    def _absX_eff(self, kind: str) -> Tuple[int, bool]:
        addr, cross = self._absX()
        if self._store_dummy_addr is not None:
            if kind == 'rmw' or (kind == 'read' and cross):
                # dummy read (does not change PC)
                self.read(self._store_dummy_addr)
        return addr, cross

    def _absY_eff(self, kind: str) -> Tuple[int, bool]:
        addr, cross = self._absY()
        if self._store_dummy_addr is not None:
            if kind == 'rmw' or (kind == 'read' and cross):
                self.read(self._store_dummy_addr)
        return addr, cross

    def _indY_eff(self, kind: str) -> Tuple[int, bool]:
        addr, cross = self._indY()
        if self._store_dummy_addr is not None:
            if kind == 'rmw' or (kind == 'read' and cross):
                self.read(self._store_dummy_addr)
        return addr, cross

    # --- Execute one instruction ---
    def step(self) -> int:
        start = self._now()
        # Start a new instruction window
        self._instr_cycles_done = 0
        self._rmw_old_write_done = False
        self._store_dummy_addr = None
        self._store_dummy_done = False
        self._instr_base = start
        self._instr_bus_i = 0
        self.bus_cycle = start
        op = self.fetch()
        self._current_op = op
        cycles = 2

        # shift/rotate helpers
        def asl(v: int) -> int:
            v &= 0xFF
            self.set_flag(Cpu6502.C, (v & 0x80) != 0)
            v = (v << 1) & 0xFF
            self.set_zn(v)
            return v

        def lsr(v: int) -> int:
            v &= 0xFF
            self.set_flag(Cpu6502.C, (v & 0x01) != 0)
            v = (v >> 1) & 0xFF
            self.set_zn(v)
            return v

        def rol(v: int) -> int:
            v &= 0xFF
            c = 1 if self.get_flag(Cpu6502.C) else 0
            self.set_flag(Cpu6502.C, (v & 0x80) != 0)
            v = ((v << 1) | c) & 0xFF
            self.set_zn(v)
            return v

        def ror(v: int) -> int:
            v &= 0xFF
            c = 0x80 if self.get_flag(Cpu6502.C) else 0
            self.set_flag(Cpu6502.C, (v & 0x01) != 0)
            v = ((v >> 1) | c) & 0xFF
            self.set_zn(v)
            return v

        # --- Decode & execute ---
        if op == 0x00:
            self.pc = _u16(self.pc + 1)
            cycles = self.irq_vector(0xFFFE, True)

        elif op == 0x40:
            self.flags = (self.pull() | Cpu6502.U) & ~Cpu6502.B
            lo = self.pull(); hi = self.pull()
            self.pc = (hi << 8) | lo
            cycles = 6

        elif op == 0x60:
            lo = self.pull(); hi = self.pull()
            self.pc = _u16(((hi << 8) | lo) + 1)
            cycles = 6

        elif op == 0xEA:
            cycles = 2

        # Flag ops
        elif op == 0x18:
            self.set_flag(Cpu6502.C, False); cycles = 2
        elif op == 0x38:
            self.set_flag(Cpu6502.C, True); cycles = 2
        elif op == 0x58:
            self.set_flag(Cpu6502.I, False); cycles = 2
        elif op == 0x78:
            self.set_flag(Cpu6502.I, True); cycles = 2
        elif op == 0xB8:
            self.set_flag(Cpu6502.V, False); cycles = 2
        elif op == 0xD8:
            self.set_flag(Cpu6502.D, False); cycles = 2
        elif op == 0xF8:
            self.set_flag(Cpu6502.D, True); cycles = 2

        # Stack
        elif op == 0x48:
            self.push(self.a); cycles = 3
        elif op == 0x68:
            self.a = self.pull(); self.set_zn(self.a); cycles = 4
        elif op == 0x08:
            self.push(self.flags | Cpu6502.B | Cpu6502.U); cycles = 3
        elif op == 0x28:
            self.flags = (self.pull() | Cpu6502.U) & ~Cpu6502.B; cycles = 4

        # Transfers
        elif op == 0xAA:
            self.x = self.a; self.set_zn(self.x); cycles = 2
        elif op == 0xA8:
            self.y = self.a; self.set_zn(self.y); cycles = 2
        elif op == 0x8A:
            self.a = self.x; self.set_zn(self.a); cycles = 2
        elif op == 0x98:
            self.a = self.y; self.set_zn(self.a); cycles = 2
        elif op == 0xBA:
            self.x = self.sp; self.set_zn(self.x); cycles = 2
        elif op == 0x9A:
            self.sp = self.x; cycles = 2

        # INC/DEC regs
        elif op == 0xE8:
            self.x = _u8(self.x + 1); self.set_zn(self.x); cycles = 2
        elif op == 0xC8:
            self.y = _u8(self.y + 1); self.set_zn(self.y); cycles = 2
        elif op == 0xCA:
            self.x = _u8(self.x - 1); self.set_zn(self.x); cycles = 2
        elif op == 0x88:
            self.y = _u8(self.y - 1); self.set_zn(self.y); cycles = 2

        # JSR/JMP
        elif op == 0x20:
            addr = self._abs()
            ret = _u16(self.pc - 1)
            self.push((ret >> 8) & 0xFF)
            self.push(ret & 0xFF)
            self.pc = addr
            cycles = 6
        elif op == 0x4C:
            self.pc = self._abs(); cycles = 3
        elif op == 0x6C:
            ptr = self._abs(); self.pc = self.read16bug(ptr); cycles = 5

        # Branches
        elif op == 0x10: cycles = self.branch(not self.get_flag(Cpu6502.N))
        elif op == 0x30: cycles = self.branch(self.get_flag(Cpu6502.N))
        elif op == 0x50: cycles = self.branch(not self.get_flag(Cpu6502.V))
        elif op == 0x70: cycles = self.branch(self.get_flag(Cpu6502.V))
        elif op == 0x90: cycles = self.branch(not self.get_flag(Cpu6502.C))
        elif op == 0xB0: cycles = self.branch(self.get_flag(Cpu6502.C))
        elif op == 0xD0: cycles = self.branch(not self.get_flag(Cpu6502.Z))
        elif op == 0xF0: cycles = self.branch(self.get_flag(Cpu6502.Z))

        # BIT
        elif op == 0x24:
            a = self._zp()
            v = self.read(a)
            self.set_flag(Cpu6502.Z, (self.a & v) == 0)
            self.set_flag(Cpu6502.N, (v & 0x80) != 0)
            self.set_flag(Cpu6502.V, (v & 0x40) != 0)
            cycles = 3
        elif op == 0x2C:
            a = self._abs()
            v = self.read(a)
            self.set_flag(Cpu6502.Z, (self.a & v) == 0)
            self.set_flag(Cpu6502.N, (v & 0x80) != 0)
            self.set_flag(Cpu6502.V, (v & 0x40) != 0)
            cycles = 4

        # Loads: LDA
        elif op == 0xA9:
            self.a = self.fetch(); self.set_zn(self.a); cycles = 2
        elif op == 0xA5:
            a = self._zp(); self.a = self.read(a); self.set_zn(self.a); cycles = 3
        elif op == 0xB5:
            a = self._zpX(); self.a = self.read(a); self.set_zn(self.a); cycles = 4
        elif op == 0xAD:
            a = self._abs(); self.a = self.read(a); self.set_zn(self.a); cycles = 4
        elif op == 0xBD:
            addr, cross = self._absX_eff('read')
            self.a = self.read(addr)
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0xB9:
            addr, cross = self._absY_eff('read')
            self.a = self.read(addr)
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0xA1:
            a = self._indX(); self.a = self.read(a); self.set_zn(self.a); cycles = 6
        elif op == 0xB1:
            addr, cross = self._indY_eff('read')
            self.a = self.read(addr)
            self.set_zn(self.a)
            cycles = 5 + (1 if cross else 0)

        # Loads: LDX
        elif op == 0xA2:
            self.x = self.fetch(); self.set_zn(self.x); cycles = 2
        elif op == 0xA6:
            a = self._zp(); self.x = self.read(a); self.set_zn(self.x); cycles = 3
        elif op == 0xB6:
            a = self._zpY(); self.x = self.read(a); self.set_zn(self.x); cycles = 4
        elif op == 0xAE:
            a = self._abs(); self.x = self.read(a); self.set_zn(self.x); cycles = 4
        elif op == 0xBE:
            addr, cross = self._absY_eff('read')
            self.x = self.read(addr)
            self.set_zn(self.x)
            cycles = 4 + (1 if cross else 0)

        # Loads: LDY
        elif op == 0xA0:
            self.y = self.fetch(); self.set_zn(self.y); cycles = 2
        elif op == 0xA4:
            a = self._zp(); self.y = self.read(a); self.set_zn(self.y); cycles = 3
        elif op == 0xB4:
            a = self._zpX(); self.y = self.read(a); self.set_zn(self.y); cycles = 4
        elif op == 0xAC:
            a = self._abs(); self.y = self.read(a); self.set_zn(self.y); cycles = 4
        elif op == 0xBC:
            addr, cross = self._absX_eff('read')
            self.y = self.read(addr)
            self.set_zn(self.y)
            cycles = 4 + (1 if cross else 0)

        # Stores: STA
        elif op == 0x85:
            a = self._zp(); self.write(a, self.a); cycles = 3
        elif op == 0x95:
            a = self._zpX(); self.write(a, self.a); cycles = 4
        elif op == 0x8D:
            a = self._abs(); self.write(a, self.a); cycles = 4
        elif op == 0x9D:
            addr, _ = self._absX(); self.write(addr, self.a); cycles = 5
        elif op == 0x99:
            addr, _ = self._absY(); self.write(addr, self.a); cycles = 5
        elif op == 0x81:
            a = self._indX(); self.write(a, self.a); cycles = 6
        elif op == 0x91:
            addr, _ = self._indY(); self.write(addr, self.a); cycles = 6

        # Stores: STX
        elif op == 0x86:
            a = self._zp(); self.write(a, self.x); cycles = 3
        elif op == 0x96:
            a = self._zpY(); self.write(a, self.x); cycles = 4
        elif op == 0x8E:
            a = self._abs(); self.write(a, self.x); cycles = 4

        # Stores: STY
        elif op == 0x84:
            a = self._zp(); self.write(a, self.y); cycles = 3
        elif op == 0x94:
            a = self._zpX(); self.write(a, self.y); cycles = 4
        elif op == 0x8C:
            a = self._abs(); self.write(a, self.y); cycles = 4

        # ORA
        elif op == 0x09:
            self.a = _u8(self.a | self.fetch()); self.set_zn(self.a); cycles = 2
        elif op == 0x05:
            a = self._zp(); self.a = _u8(self.a | self.read(a)); self.set_zn(self.a); cycles = 3
        elif op == 0x15:
            a = self._zpX(); self.a = _u8(self.a | self.read(a)); self.set_zn(self.a); cycles = 4
        elif op == 0x0D:
            a = self._abs(); self.a = _u8(self.a | self.read(a)); self.set_zn(self.a); cycles = 4
        elif op == 0x1D:
            addr, cross = self._absX_eff('read')
            self.a = _u8(self.a | self.read(addr))
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0x19:
            addr, cross = self._absY_eff('read')
            self.a = _u8(self.a | self.read(addr))
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0x01:
            a = self._indX(); self.a = _u8(self.a | self.read(a)); self.set_zn(self.a); cycles = 6
        elif op == 0x11:
            addr, cross = self._indY_eff('read')
            self.a = _u8(self.a | self.read(addr))
            self.set_zn(self.a)
            cycles = 5 + (1 if cross else 0)

        # AND
        elif op == 0x29:
            self.a = _u8(self.a & self.fetch()); self.set_zn(self.a); cycles = 2
        elif op == 0x25:
            a = self._zp(); self.a = _u8(self.a & self.read(a)); self.set_zn(self.a); cycles = 3
        elif op == 0x35:
            a = self._zpX(); self.a = _u8(self.a & self.read(a)); self.set_zn(self.a); cycles = 4
        elif op == 0x2D:
            a = self._abs(); self.a = _u8(self.a & self.read(a)); self.set_zn(self.a); cycles = 4
        elif op == 0x3D:
            addr, cross = self._absX_eff('read')
            self.a = _u8(self.a & self.read(addr))
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0x39:
            addr, cross = self._absY_eff('read')
            self.a = _u8(self.a & self.read(addr))
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0x21:
            a = self._indX(); self.a = _u8(self.a & self.read(a)); self.set_zn(self.a); cycles = 6
        elif op == 0x31:
            addr, cross = self._indY_eff('read')
            self.a = _u8(self.a & self.read(addr))
            self.set_zn(self.a)
            cycles = 5 + (1 if cross else 0)

        # EOR
        elif op == 0x49:
            self.a = _u8(self.a ^ self.fetch()); self.set_zn(self.a); cycles = 2
        elif op == 0x45:
            a = self._zp(); self.a = _u8(self.a ^ self.read(a)); self.set_zn(self.a); cycles = 3
        elif op == 0x55:
            a = self._zpX(); self.a = _u8(self.a ^ self.read(a)); self.set_zn(self.a); cycles = 4
        elif op == 0x4D:
            a = self._abs(); self.a = _u8(self.a ^ self.read(a)); self.set_zn(self.a); cycles = 4
        elif op == 0x5D:
            addr, cross = self._absX_eff('read')
            self.a = _u8(self.a ^ self.read(addr))
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0x59:
            addr, cross = self._absY_eff('read')
            self.a = _u8(self.a ^ self.read(addr))
            self.set_zn(self.a)
            cycles = 4 + (1 if cross else 0)
        elif op == 0x41:
            a = self._indX(); self.a = _u8(self.a ^ self.read(a)); self.set_zn(self.a); cycles = 6
        elif op == 0x51:
            addr, cross = self._indY_eff('read')
            self.a = _u8(self.a ^ self.read(addr))
            self.set_zn(self.a)
            cycles = 5 + (1 if cross else 0)

        # ADC
        elif op == 0x69:
            self.adc(self.fetch()); cycles = 2
        elif op == 0x65:
            a = self._zp(); self.adc(self.read(a)); cycles = 3
        elif op == 0x75:
            a = self._zpX(); self.adc(self.read(a)); cycles = 4
        elif op == 0x6D:
            a = self._abs(); self.adc(self.read(a)); cycles = 4
        elif op == 0x7D:
            addr, cross = self._absX_eff('read')
            self.adc(self.read(addr))
            cycles = 4 + (1 if cross else 0)
        elif op == 0x79:
            addr, cross = self._absY_eff('read')
            self.adc(self.read(addr))
            cycles = 4 + (1 if cross else 0)
        elif op == 0x61:
            a = self._indX(); self.adc(self.read(a)); cycles = 6
        elif op == 0x71:
            addr, cross = self._indY_eff('read')
            self.adc(self.read(addr))
            cycles = 5 + (1 if cross else 0)

        # SBC
        elif op == 0xE9:
            self.sbc(self.fetch()); cycles = 2
        elif op == 0xE5:
            a = self._zp(); self.sbc(self.read(a)); cycles = 3
        elif op == 0xF5:
            a = self._zpX(); self.sbc(self.read(a)); cycles = 4
        elif op == 0xED:
            a = self._abs(); self.sbc(self.read(a)); cycles = 4
        elif op == 0xFD:
            addr, cross = self._absX_eff('read')
            self.sbc(self.read(addr))
            cycles = 4 + (1 if cross else 0)
        elif op == 0xF9:
            addr, cross = self._absY_eff('read')
            self.sbc(self.read(addr))
            cycles = 4 + (1 if cross else 0)
        elif op == 0xE1:
            a = self._indX(); self.sbc(self.read(a)); cycles = 6
        elif op == 0xF1:
            addr, cross = self._indY_eff('read')
            self.sbc(self.read(addr))
            cycles = 5 + (1 if cross else 0)

        # BIT
        elif op == 0x24:
            a = self._zp(); v = self.read(a); self.set_flag(Cpu6502.Z, (self.a & v) == 0); self.set_flag(Cpu6502.V, (v & 0x40) != 0); self.set_flag(Cpu6502.N, (v & 0x80) != 0); cycles = 3
        elif op == 0x2C:
            a = self._abs(); v = self.read(a); self.set_flag(Cpu6502.Z, (self.a & v) == 0); self.set_flag(Cpu6502.V, (v & 0x40) != 0); self.set_flag(Cpu6502.N, (v & 0x80) != 0); cycles = 4

        # CMP/CPX/CPY
        elif op == 0xC9:
            self.cmp(self.a, self.fetch()); cycles = 2
        elif op == 0xC5:
            a = self._zp(); self.cmp(self.a, self.read(a)); cycles = 3
        elif op == 0xD5:
            a = self._zpX(); self.cmp(self.a, self.read(a)); cycles = 4
        elif op == 0xCD:
            a = self._abs(); self.cmp(self.a, self.read(a)); cycles = 4
        elif op == 0xDD:
            addr, cross = self._absX_eff('read')
            self.cmp(self.a, self.read(addr))
            cycles = 4 + (1 if cross else 0)
        elif op == 0xD9:
            addr, cross = self._absY_eff('read')
            self.cmp(self.a, self.read(addr))
            cycles = 4 + (1 if cross else 0)
        elif op == 0xC1:
            a = self._indX(); self.cmp(self.a, self.read(a)); cycles = 6
        elif op == 0xD1:
            addr, cross = self._indY_eff('read')
            self.cmp(self.a, self.read(addr))
            cycles = 5 + (1 if cross else 0)

        elif op == 0xE0:
            self.cmp(self.x, self.fetch()); cycles = 2
        elif op == 0xE4:
            a = self._zp(); self.cmp(self.x, self.read(a)); cycles = 3
        elif op == 0xEC:
            a = self._abs(); self.cmp(self.x, self.read(a)); cycles = 4

        elif op == 0xC0:
            self.cmp(self.y, self.fetch()); cycles = 2
        elif op == 0xC4:
            a = self._zp(); self.cmp(self.y, self.read(a)); cycles = 3
        elif op == 0xCC:
            a = self._abs(); self.cmp(self.y, self.read(a)); cycles = 4

        # INC/DEC memory
        elif op == 0xE6:
            a = self._zp(); v = _u8(self.read(a) + 1); self.write(a, v); self.set_zn(v); cycles = 5
        elif op == 0xF6:
            a = self._zpX(); v = _u8(self.read(a) + 1); self.write(a, v); self.set_zn(v); cycles = 6
        elif op == 0xEE:
            a = self._abs(); v = _u8(self.read(a) + 1); self.write(a, v); self.set_zn(v); cycles = 6
        elif op == 0xFE:
            addr, _ = self._absX_eff('rmw')
            v = _u8(self.read(addr) + 1)
            self.write(addr, v)
            self.set_zn(v)
            cycles = 7

        elif op == 0xC6:
            a = self._zp(); v = _u8(self.read(a) - 1); self.write(a, v); self.set_zn(v); cycles = 5
        elif op == 0xD6:
            a = self._zpX(); v = _u8(self.read(a) - 1); self.write(a, v); self.set_zn(v); cycles = 6
        elif op == 0xCE:
            a = self._abs(); v = _u8(self.read(a) - 1); self.write(a, v); self.set_zn(v); cycles = 6
        elif op == 0xDE:
            addr, _ = self._absX_eff('rmw')
            v = _u8(self.read(addr) - 1)
            self.write(addr, v)
            self.set_zn(v)
            cycles = 7

        # ASL/LSR/ROL/ROR accumulator
        elif op == 0x0A:
            self.a = asl(self.a); cycles = 2
        elif op == 0x4A:
            self.a = lsr(self.a); cycles = 2
        elif op == 0x2A:
            self.a = rol(self.a); cycles = 2
        elif op == 0x6A:
            self.a = ror(self.a); cycles = 2

        # ASL memory
        elif op == 0x06:
            a = self._zp(); v = asl(self.read(a)); self.write(a, v); cycles = 5
        elif op == 0x16:
            a = self._zpX(); v = asl(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x0E:
            a = self._abs(); v = asl(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x1E:
            addr, _ = self._absX_eff('rmw')
            v = asl(self.read(addr))
            self.write(addr, v)
            cycles = 7

        # LSR memory
        elif op == 0x46:
            a = self._zp(); v = lsr(self.read(a)); self.write(a, v); cycles = 5
        elif op == 0x56:
            a = self._zpX(); v = lsr(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x4E:
            a = self._abs(); v = lsr(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x5E:
            addr, _ = self._absX_eff('rmw')
            v = lsr(self.read(addr))
            self.write(addr, v)
            cycles = 7

        # ROL memory
        elif op == 0x26:
            a = self._zp(); v = rol(self.read(a)); self.write(a, v); cycles = 5
        elif op == 0x36:
            a = self._zpX(); v = rol(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x2E:
            a = self._abs(); v = rol(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x3E:
            addr, _ = self._absX_eff('rmw')
            v = rol(self.read(addr))
            self.write(addr, v)
            cycles = 7

        # ROR memory
        elif op == 0x66:
            a = self._zp(); v = ror(self.read(a)); self.write(a, v); cycles = 5
        elif op == 0x76:
            a = self._zpX(); v = ror(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x6E:
            a = self._abs(); v = ror(self.read(a)); self.write(a, v); cycles = 6
        elif op == 0x7E:
            addr, _ = self._absX_eff('rmw')
            v = ror(self.read(addr))
            self.write(addr, v)
            cycles = 7

        else:
            info = CpuIllegals.get_instruction_info(op)
            if info:
                addr = 0
                val = 0
                do_exec = True

                # Immediate mode opcodes (ANC, ALR, ARR, AXS)
                if op in (0x0B, 0x2B, 0x4B, 0x6B, 0xCB):
                    val = self.fetch()
                # Decode addressing mode by exact opcode sets
                # zp
                elif op in (0xA7, 0xC7, 0xE7, 0x07, 0x27, 0x47, 0x67, 0x87):
                    addr = self._zp(); val = self.read(addr)
                # zp,X (RMW illegals)
                elif op in (0xD7, 0xF7, 0x17, 0x37, 0x57, 0x77):
                    addr = self._zpX(); val = self.read(addr)
                # zp,Y (LAX/SAX)
                elif op in (0xB7, 0x97):
                    addr = self._zpY(); val = self.read(addr)
                # abs
                elif op in (0xAF, 0xCF, 0xEF, 0x0F, 0x2F, 0x4F, 0x6F, 0x8F):
                    addr = self._abs(); val = self.read(addr)
                # abs,X (RMW illegals)
                elif op in (0xDF, 0xFF, 0x1F, 0x3F, 0x5F, 0x7F):
                    addr, _ = self._absX_eff('rmw')
                    val = self.read(addr)
                # abs,Y (mix of reads and RMW illegals)
                elif op in (0xBF, 0xBB):
                    # LAX/LAS abs,Y are reads with page-cross penalty
                    addr, _ = self._absY_eff('read')
                    val = self.read(addr)
                elif op in (0xDB, 0xFB, 0x1B, 0x3B, 0x5B, 0x7B):
                    # DCP/ISC/SLO/RLA/SRE/RRA abs,Y are RMW
                    addr, _ = self._absY_eff('rmw')
                    val = self.read(addr)
                # (ind,X)
                elif op in (0xA3, 0xC3, 0xE3, 0x03, 0x23, 0x43, 0x63, 0x83):
                    addr = self._indX(); val = self.read(addr)
                # (ind),Y
                elif op == 0xB3:
                    # LAX (ind),Y is a read with page-cross penalty
                    addr, _ = self._indY_eff('read')
                    val = self.read(addr)
                elif op in (0xD3, 0xF3, 0x13, 0x33, 0x53, 0x73):
                    # DCP/ISC/SLO/RLA/SRE/RRA (ind),Y are RMW
                    addr, _ = self._indY_eff('rmw')
                    val = self.read(addr)
                else:
                    # Unknown illegal variant; treat as 2-cycle NOP.
                    cycles = 2
                    do_exec = False

                if do_exec:
                    CpuIllegals.execute(self, op, addr, val)
                    cycles = info.cycles if info.cycles is not None else cycles
            else:
                # Handle NOP variants with correct cycle timing
                if op in (0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xEA, 0xFA):
                    # 1-byte NOPs (2 cycles)
                    cycles = 2
                elif op in (0x80, 0x82, 0x89, 0xC2, 0xE2):
                    # 2-byte NOPs with immediate (2 cycles)
                    self.fetch()
                    cycles = 2
                elif op in (0x04, 0x44, 0x64):
                    # 2-byte NOPs with zero page (3 cycles)
                    a = self._zp(); self.read(a)
                    cycles = 3
                elif op in (0x14, 0x34, 0x54, 0x74, 0xD4, 0xF4):
                    # 2-byte NOPs with zero page,X (4 cycles)
                    a = self._zpX(); self.read(a)
                    cycles = 4
                elif op in (0x0C,):
                    # 3-byte NOP with absolute (4 cycles)
                    a = self._abs(); self.read(a)
                    cycles = 4
                elif op in (0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC):
                    # 3-byte NOPs with absolute,X (4 or 5 cycles with page cross)
                    addr, cross = self._absX_eff('read')
                    self.read(addr)
                    cycles = 4 + (1 if cross else 0)
                else:
                    # Truly unknown opcodes - treat as 2-cycle NOP
                    cycles = 2

        # Consume remaining CPU bus cycles so the bus timeline is complete.
        # NOTE: BA/RDY stalls are handled by the Bus and will extend wall-time.
        while self._instr_cycles_done < cycles:
            self.idle_cycle(self.pc)

        end = self._now()
        self.cycles = end
        self.bus_cycle = end
        return end - start
