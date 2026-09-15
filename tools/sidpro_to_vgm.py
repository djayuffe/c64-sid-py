#!/usr/bin/env python3
"""Explain why SID-PRO write traces cannot be exported as standard VGM."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from c64sid.sid.sidpro_forensic import SIDProForensicExport


def write_vgm(export: SIDProForensicExport, output_path: str):
    """Reject an invalid conversion instead of emitting corrupt VGM data.

    VGM has no SID chip definition. Command 0x50 targets the SN76489 and takes
    one byte, so using it for SID register/value pairs creates malformed output.
    Use the CSV exporter or the binary SID-PRO format for lossless SID writes.
    """
    raise ValueError(
        'Standard VGM has no SID chip command; refusing to create an invalid .vgm. '
        'Use tools/sidpro_to_csv.py or retain the SID-PRO capture.'
    )


def main():
    parser = argparse.ArgumentParser(description='Convert SID-PRO to VGM')
    parser.add_argument('input_sidpro', help='Input .sidpro file')
    parser.add_argument('output_vgm', help='Output .vgm file')
    args = parser.parse_args()

    print(f"Loading {args.input_sidpro}...")
    export = SIDProForensicExport.load_from_file(args.input_sidpro)

    try:
        write_vgm(export, args.output_vgm)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
