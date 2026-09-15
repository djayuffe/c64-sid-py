from __future__ import annotations

from ..logger import SystemLogger
from .vic_ii import VicII


class VicDma:
    """
    VIC-II DMA / BA (Bus Available) model.

    This emulator uses a *cycle-granular* CPU clock. We approximate BA low periods:
      - On bad lines, VIC steals 40 cycles for character fetch.
      - The canonical PAL badline window is cycles 15..54 (40 cycles).
    """

    @staticmethod
    def is_bad_line(vic: VicII) -> bool:
        ctrl1 = vic.read(0x11)
        raster = vic.rasterLine
        # Display enabled?
        if (ctrl1 & 0x10) == 0:
            return False
        y_scroll = ctrl1 & 0x07
        if (raster & 0x07) != y_scroll:
            return False
        # Visible area raster range (approx)
        return 0x30 <= raster <= 0xF7

    @staticmethod
    def ba_low(vic: VicII) -> bool:
        """Return True if BA is low (CPU stalled) for the current raster cycle."""
        if not VicDma.is_bad_line(vic):
            return False
        cycle_in_line = vic.cycleCounter % max(1, vic.cyclesPerLine)
        return 15 <= cycle_in_line <= 54

    @staticmethod
    def calculate_stolen_cycles(vic: VicII) -> int:
        # legacy API (kept for compatibility) — total stolen cycles per badline
        return 40 if VicDma.is_bad_line(vic) else 0
