"""Human-readable CIA register names for diagnostics and trace tools."""
from __future__ import annotations


_CIA_REGISTER_NAMES = (
    'PRA', 'PRB', 'DDRA', 'DDRB', 'TALO', 'TAHI', 'TBLO', 'TBHI',
    'TOD_10THS', 'TOD_SEC', 'TOD_MIN', 'TOD_HR', 'SDR', 'ICR', 'CRA', 'CRB',
)


def get_cia_reg_name(offset: int) -> str:
    """Return the canonical CIA register name for a mirrored address offset."""
    register = int(offset) & 0x0F
    return _CIA_REGISTER_NAMES[register]


def analyze_cia_write(offset: int, value: int) -> str:
    """Summarize a CIA control-register write for diagnostic output."""
    register = int(offset) & 0x0F
    byte = int(value) & 0xFF
    if register == 0x0D:
        return f"{'set' if byte & 0x80 else 'clear'} mask bits=%{byte & 0x1F:05b}"
    if register in (0x0E, 0x0F):
        return (
            f"start={byte & 1} oneshot={(byte >> 3) & 1} load={(byte >> 4) & 1} "
            f"input_mode={(byte >> 5) & 0x03}"
        )
    return ''
