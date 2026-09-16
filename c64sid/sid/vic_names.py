"""Human-readable VIC-II register names for diagnostics and trace tools."""
from __future__ import annotations


_VIC_REGISTER_NAMES = {
    0x10: 'SPR_X_MSB', 0x11: 'CTRL1', 0x12: 'RASTER', 0x13: 'LPEN_X',
    0x14: 'LPEN_Y', 0x15: 'SPR_ENABLE', 0x16: 'CTRL2', 0x17: 'SPR_Y_EXPAND',
    0x18: 'MEM_PTRS', 0x19: 'IRQ_STATUS', 0x1A: 'IRQ_MASK', 0x1B: 'SPR_PRIORITY',
    0x1C: 'SPR_MULTICOLOR', 0x1D: 'SPR_X_EXPAND', 0x1E: 'SPR_SPR_COLL',
    0x1F: 'SPR_BG_COLL', 0x20: 'BORDER', 0x21: 'BG0', 0x22: 'BG1', 0x23: 'BG2',
    0x24: 'BG3', 0x25: 'SPR_MC0', 0x26: 'SPR_MC1',
}
_VIC_REGISTER_NAMES.update({index: f'SPR{index // 2}_{"X" if index % 2 == 0 else "Y"}' for index in range(0x10)})
_VIC_REGISTER_NAMES.update({index: f'SPR{index - 0x27}_COLOR' for index in range(0x27, 0x2F)})


def get_vic_reg_name(offset: int) -> str:
    """Return the canonical VIC-II register name for a mirrored address offset."""
    register = int(offset) & 0x3F
    return _VIC_REGISTER_NAMES.get(register, f'VIC_${register:02X}')


def analyze_vic_write(offset: int, value: int) -> str:
    """Summarize selected VIC-II writes for diagnostic output."""
    register = int(offset) & 0x3F
    byte = int(value) & 0xFF
    if register == 0x11:
        return f'den={(byte >> 4) & 1} bmm={(byte >> 5) & 1} ecm={(byte >> 6) & 1} yscroll={byte & 7}'
    if register == 0x16:
        return f'mcm={(byte >> 4) & 1} csel={(byte >> 3) & 1} xscroll={byte & 7}'
    if register == 0x18:
        return f'video_matrix=${(byte >> 4) & 0x0F:X}000 char_base=${(byte >> 1) & 7:X}000'
    if register in (0x19, 0x1A):
        return f'maskbits=%{byte & 0x0F:04b} master={(byte >> 7) & 1}'
    return ''
