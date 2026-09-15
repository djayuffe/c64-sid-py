"""Compatibility wrapper for SID-PRO forensic exports.

The SIDPRO_FORMAT.md specification expects:
    from sidpro_forensic import SIDProForensicExport

The implementation lives in c64sid.sid.sidpro_forensic.
"""

from c64sid.sid.sidpro_forensic import SIDProForensicExport, SIDPRO_VERSION

__all__ = ["SIDProForensicExport", "SIDPRO_VERSION"]
