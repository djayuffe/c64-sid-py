from __future__ import annotations

from ..logger import SystemLogger


def _u8(v: int) -> int:
    return v & 0xFF


def _u16(v: int) -> int:
    return v & 0xFFFF


def _bcd_to_int(v: int) -> int:
    v &= 0xFF
    return ((v >> 4) & 0x0F) * 10 + (v & 0x0F)


def _int_to_bcd(n: int) -> int:
    n = max(0, int(n))
    return ((n // 10) << 4) | (n % 10)


class Cia6526:
    """MOS 6526 CIA (timers + ports + TOD + serial) - pragmatic, bus-visible.

    Notes:
    - Timers are stepped at 1 tick per CPU cycle (PHI2).
    - CNT modes are supported via an optional cnt_edge input to step().
    - TOD is derived from CPU clock using CRA bit7 (50/60 Hz select).
    - Serial SDR is modeled as an 8-bit shift completing on Timer A underflows.
    """

    def __init__(self, name: str, clock_hz: int = 985248):
        self.name = name
        self.clock_hz = int(clock_hz)

        # Ports
        self.pra = 0xFF
        self.prb = 0xFF
        self.ddra = 0x00
        self.ddrb = 0x00

        # Timers
        self.latchA = 0xFFFF
        self.latchB = 0xFFFF
        self.timerA = 0xFFFF
        self.timerB = 0xFFFF

        # TOD clock (BCD)
        self.tod_tenths = 0x00
        self.tod_sec = 0x00
        self.tod_min = 0x00
        self.tod_hour = 0x00
        self.alarm_tenths = 0x00
        self.alarm_sec = 0x00
        self.alarm_min = 0x00
        self.alarm_hour = 0x00

        self._tod_cycle_accum = 0.0
        self._tod_pulse_count = 0

        # Serial
        self.sdr = 0xFF
        self._serial_bits_remaining = 0

        # Interrupts
        self.icr = 0
        self.icrMask = 0
        self.cra = 0
        self.crb = 0
        self.irqLine = False

    def reset(self) -> None:
        self.pra = 0xFF
        self.prb = 0xFF
        self.ddra = 0x00
        self.ddrb = 0x00

        self.latchA = 0xFFFF
        self.latchB = 0xFFFF
        self.timerA = 0xFFFF
        self.timerB = 0xFFFF

        self.tod_tenths = 0x00
        self.tod_sec = 0x00
        self.tod_min = 0x00
        self.tod_hour = 0x00
        self.alarm_tenths = 0x00
        self.alarm_sec = 0x00
        self.alarm_min = 0x00
        self.alarm_hour = 0x00
        self._tod_cycle_accum = 0.0
        self._tod_pulse_count = 0

        self.sdr = 0xFF
        self._serial_bits_remaining = 0

        self.icr = 0
        self.icrMask = 0
        self.cra = 0
        self.crb = 0
        self.irqLine = False

        SystemLogger.log('CIA', f'[{self.name}] Hardware Reset.', 'debug')

    def peek_icr(self) -> int:
        return self.icr & 0x1F

    def _tod_pulses_per_second(self) -> int:
        # CIA TOD 50/60 select is CRA bit7 (1=50Hz, 0=60Hz)
        return 50 if (self.cra & 0x80) else 60

    def _tick_tod(self) -> None:
        # Derive mains pulse from CPU clock.
        pps = self._tod_pulses_per_second()
        if pps <= 0:
            return
        cycles_per_pulse = float(self.clock_hz) / float(pps)
        self._tod_cycle_accum += 1.0
        if self._tod_cycle_accum < cycles_per_pulse:
            return
        self._tod_cycle_accum -= cycles_per_pulse
        self._tod_pulse_count += 1
        div = 5 if pps == 50 else 6  # 50/60 Hz -> tenths (10 Hz)
        if self._tod_pulse_count < div:
            return
        self._tod_pulse_count = 0

        # Increment BCD tenths/seconds/minutes/hours (24h pragmatic)
        t = _bcd_to_int(self.tod_tenths) + 1
        s = _bcd_to_int(self.tod_sec)
        m = _bcd_to_int(self.tod_min)
        h = _bcd_to_int(self.tod_hour)

        if t >= 10:
            t = 0
            s += 1
        if s >= 60:
            s = 0
            m += 1
        if m >= 60:
            m = 0
            h = (h + 1) % 24

        self.tod_tenths = _int_to_bcd(t)
        self.tod_sec = _int_to_bcd(s)
        self.tod_min = _int_to_bcd(m)
        self.tod_hour = _int_to_bcd(h)

        # Alarm compare
        if (
            self.tod_tenths == self.alarm_tenths
            and self.tod_sec == self.alarm_sec
            and self.tod_min == self.alarm_min
            and self.tod_hour == self.alarm_hour
        ):
            self.icr |= 0x04  # Alarm

    def step(self, cycles: int, cnt_edges: int = 0) -> None:
        # cnt_edges: number of CNT rising edges to distribute over this step.
        edges_left = max(0, int(cnt_edges))
        for _ in range(max(0, int(cycles))):
            cnt_edge = False
            if edges_left > 0:
                cnt_edge = True
                edges_left -= 1

            underflowA = self._tick_timer_a(cnt_edge)
            self._tick_timer_b(underflowA, cnt_edge)
            self._tick_tod()
        self._update_irq_line()

    def _tick_timer_a(self, cnt_edge: bool) -> bool:
        if (self.cra & 0x01) == 0:
            return False

        # CRA bit5 selects CNT input instead of PHI2.
        if (self.cra & 0x20) != 0 and not cnt_edge:
            return False

        self.timerA = _u16(self.timerA - 1)
        if self.timerA == 0xFFFF:
            self.icr |= 0x01
            self.timerA = self.latchA & 0xFFFF
            if (self.cra & 0x08) != 0:
                self.cra &= ~0x01

            # Serial: complete 8-bit shift on Timer A underflows.
            if self._serial_bits_remaining > 0:
                self._serial_bits_remaining -= 1
                if self._serial_bits_remaining == 0:
                    self.icr |= 0x08  # Serial complete

            return True
        return False

    def _tick_timer_b(self, underflowA: bool, cnt_edge: bool) -> None:
        if (self.crb & 0x01) == 0:
            return
        input_mode = (self.crb >> 5) & 0x03
        tickB = False

        if input_mode == 0:
            tickB = True
        elif input_mode == 1:
            tickB = cnt_edge
        elif input_mode == 2:
            tickB = underflowA
        elif input_mode == 3:
            tickB = underflowA and cnt_edge

        if not tickB:
            return

        self.timerB = _u16(self.timerB - 1)
        if self.timerB == 0xFFFF:
            self.icr |= 0x02
            self.timerB = self.latchB & 0xFFFF
            if (self.crb & 0x08) != 0:
                self.crb &= ~0x01

    def _update_irq_line(self) -> None:
        active = ((self.icr & self.icrMask) & 0x1F) != 0
        self.irqLine = bool(active)

    def read(self, addr: int, bus_val: int = 0xFF) -> int:
        reg = addr & 0x0F
        if reg == 0x0D:
            flags = self.icr & 0x1F
            master = 0x80 if ((flags & (self.icrMask & 0x1F)) != 0) else 0
            val = (flags | master) & 0xFF
            # Reading ICR clears pending flags.
            self.icr = 0
            self.irqLine = False
            return val

        if reg == 0x00:
            return ((self.pra & self.ddra) | (0xFF & (~self.ddra & 0xFF))) & 0xFF
        if reg == 0x01:
            return ((self.prb & self.ddrb) | (0xFF & (~self.ddrb & 0xFF))) & 0xFF
        if reg == 0x02:
            return self.ddra & 0xFF
        if reg == 0x03:
            return self.ddrb & 0xFF
        if reg == 0x04:
            return self.timerA & 0xFF
        if reg == 0x05:
            return (self.timerA >> 8) & 0xFF
        if reg == 0x06:
            return self.timerB & 0xFF
        if reg == 0x07:
            return (self.timerB >> 8) & 0xFF

        # TOD clock
        if reg == 0x08:
            return self.tod_tenths & 0xFF
        if reg == 0x09:
            return self.tod_sec & 0xFF
        if reg == 0x0A:
            return self.tod_min & 0xFF
        if reg == 0x0B:
            return self.tod_hour & 0xFF

        # Serial Data Register
        if reg == 0x0C:
            return self.sdr & 0xFF

        if reg == 0x0E:
            return self.cra & 0xFF
        if reg == 0x0F:
            return self.crb & 0xFF

        # Unhandled register: open bus
        return _u8(bus_val)

    def write(self, addr: int, val: int) -> None:
        reg = addr & 0x0F
        v = _u8(val)

        if reg == 0x0D:
            # Interrupt mask set/clear
            if v & 0x80:
                self.icrMask |= (v & 0x1F)
            else:
                self.icrMask &= ~(v & 0x1F)
            self._update_irq_line()
            return

        # Ports
        if reg == 0x00:
            self.pra = v
            return
        if reg == 0x01:
            self.prb = v
            return
        if reg == 0x02:
            self.ddra = v
            return
        if reg == 0x03:
            self.ddrb = v
            return

        # Timers latch
        if reg == 0x04:
            self.latchA = (self.latchA & 0xFF00) | v
            return
        if reg == 0x05:
            self.latchA = (self.latchA & 0x00FF) | (v << 8)
            if (self.cra & 0x01) == 0:
                self.timerA = self.latchA & 0xFFFF
            return
        if reg == 0x06:
            self.latchB = (self.latchB & 0xFF00) | v
            return
        if reg == 0x07:
            self.latchB = (self.latchB & 0x00FF) | (v << 8)
            if (self.crb & 0x01) == 0:
                self.timerB = self.latchB & 0xFFFF
            return

        # TOD / Alarm registers
        if reg in (0x08, 0x09, 0x0A, 0x0B):
            alarm_mode = (self.crb & 0x80) != 0
            if alarm_mode:
                if reg == 0x08:
                    self.alarm_tenths = v
                elif reg == 0x09:
                    self.alarm_sec = v
                elif reg == 0x0A:
                    self.alarm_min = v
                elif reg == 0x0B:
                    self.alarm_hour = v
            else:
                if reg == 0x08:
                    self.tod_tenths = v
                elif reg == 0x09:
                    self.tod_sec = v
                elif reg == 0x0A:
                    self.tod_min = v
                elif reg == 0x0B:
                    self.tod_hour = v
            return

        # Serial Data Register
        if reg == 0x0C:
            self.sdr = v
            self._serial_bits_remaining = 8
            return

        # Control A
        if reg == 0x0E:
            load = (v & 0x10) != 0
            self.cra = v & ~0x10
            if load:
                self.timerA = self.latchA & 0xFFFF
            self._update_irq_line()
            return

        # Control B
        if reg == 0x0F:
            load = (v & 0x10) != 0
            self.crb = v & ~0x10
            if load:
                self.timerB = self.latchB & 0xFFFF
            self._update_irq_line()
            return
