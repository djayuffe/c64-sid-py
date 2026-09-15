from __future__ import annotations

import math
from typing import List

SID_REG_NAMES: List[str] = [
    'V1_FREQ_LO', 'V1_FREQ_HI', 'V1_PULSE_LO', 'V1_PULSE_HI', 'V1_CTRL', 'V1_ATK_DECY', 'V1_STN_RELS',
    'V2_FREQ_LO', 'V2_FREQ_HI', 'V2_PULSE_LO', 'V2_PULSE_HI', 'V2_CTRL', 'V2_ATK_DECY', 'V2_STN_RELS',
    'V3_FREQ_LO', 'V3_FREQ_HI', 'V3_PULSE_LO', 'V3_PULSE_HI', 'V3_CTRL', 'V3_ATK_DECY', 'V3_STN_RELS',
    'FLTR_CUT_LO', 'FLTR_CUT_HI', 'FLTR_RESO_RTE', 'MASTER_VOL_DIGI',
    'POT_X', 'POT_Y', 'OSC3_RAND', 'ENV3'
]

NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-"]
_reg_cache = bytearray(32)


def get_sid_reg_name(reg: int) -> str:
    r = reg & 0x1F
    if r >= len(SID_REG_NAMES):
        return f"MIRROR_{r:02X}"
    return SID_REG_NAMES[r]


def analyze_sid_write(reg: int, val: int, clock_freq: int = 985_248) -> str:
    r = reg & 0x1F
    v = val & 0xFF
    _reg_cache[r] = v

    if (r % 7 == 4) and (r < 21):
        wf = []
        if v & 0x10: wf.append('TRI')
        if v & 0x20: wf.append('SAW')
        if v & 0x40: wf.append('PUL')
        if v & 0x80: wf.append('NOI')
        flags = []
        if v & 0x01: flags.append('GATE')
        if v & 0x02: flags.append('SYNC')
        if v & 0x04: flags.append('RING')
        if v & 0x08: flags.append('TEST')
        return f"WF:[{'+'.join(wf) if wf else 'OFF'}] {('|'.join(flags) if flags else 'IDLE')}"

    if (r % 7 == 5) and (r < 21):
        atk_tab = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]
        dcy_tab = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]
        atk = atk_tab[v >> 4]
        dcy = dcy_tab[v & 0x0F]
        return f"A:{atk}ms D:{dcy}ms"

    if (r % 7 == 6) and (r < 21):
        rel_tab = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]
        rel = rel_tab[v & 0x0F]
        sus = (v >> 4) / 15 * 100
        return f"S:{sus:.0f}% R:{rel}ms"

    if r in (0, 1, 7, 8, 14, 15):
        base = (r // 7) * 7
        full_freq = _reg_cache[base] | (_reg_cache[base + 1] << 8)
        hz = (full_freq * clock_freq) / 16777216
        if hz < 1:
            return f"FREQ: ${full_freq:04X} (DC)"
        midi = 69 + 12 * math.log2(hz / 440.0)
        note_idx = int(round(midi)) % 12
        octv = int(math.floor(round(midi) / 12) - 1)
        return f"{hz:.1f}Hz [{NOTE_NAMES[note_idx]}{octv}]"

    if r in (2, 3, 9, 10, 16, 17):
        base = (r // 7) * 7 + 2
        full_pw = _reg_cache[base] | ((_reg_cache[base + 1] & 0x0F) << 8)
        duty = full_pw / 40.95
        return f"PW: {duty:.1f}%"

    if r in (21, 22):
        full_cut = (_reg_cache[21] & 7) | (_reg_cache[22] << 3)
        hz = 30 + (full_cut * 5.8)
        return f"FC: ~{int(round(hz))}Hz"

    if r == 23:
        routes = []
        if v & 0x01: routes.append('V1')
        if v & 0x02: routes.append('V2')
        if v & 0x04: routes.append('V3')
        if v & 0x08: routes.append('EXT')
        return f"RES:{v >> 4} RT:[{'|'.join(routes) if routes else 'BYP'}]"

    if r == 24:
        modes = []
        if v & 0x10: modes.append('LP')
        if v & 0x20: modes.append('BP')
        if v & 0x40: modes.append('HP')
        if v & 0x80: modes.append('3OFF')
        return f"PCM_DAC:{v & 0x0F} FILT:[{'+'.join(modes) if modes else 'BYP'}]"

    return f"${v:02X}"
