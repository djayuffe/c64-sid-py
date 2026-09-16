"""Packaged reSID combined-waveform measurement tables."""
from __future__ import annotations

from functools import lru_cache
from importlib import resources


_WAVEFORM_FILES = {
    0x30: '__ST',  # saw + triangle
    0x50: '_P_T',  # pulse + triangle
    0x60: '_PS_',  # pulse + saw
    0x70: '_PST',  # pulse + saw + triangle
}


@lru_cache(maxsize=None)
def load_combined_waveform_table(model: str, waveform: int) -> tuple[int, ...] | None:
    """Return a 4096-entry 12-bit reSID table, if one is packaged.

    The source files store measured seven-bit DAC levels.  Scaling them here
    keeps every caller in the 0..4095 DAC domain used by the SID renderer.
    """
    suffix = _WAVEFORM_FILES.get(int(waveform) & 0x70)
    if model not in ('6581', '8580') or suffix is None:
        return None
    try:
        data = resources.files(__name__).joinpath(f'wave{model}{suffix}.dat').read_bytes()
    except OSError:
        return None
    if len(data) != 4096 or any(value > 127 for value in data):
        return None
    return tuple((value * 4095) // 127 for value in data)
