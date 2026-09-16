#!/usr/bin/env python3
"""Inspect a SID file through the maintained parser API."""
from __future__ import annotations

import argparse
from pathlib import Path

from c64sid.sid.sid_parser import parse_sid_header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_sid', help='Input PSID or RSID file')
    args = parser.parse_args()

    header, payload = parse_sid_header(Path(args.input_sid).read_bytes())
    print(f'{header.magic} v{header.version}: {header.title or "(untitled)"}')
    print(f'Songs: 1-{header.songs}; default: {header.startSong}')
    print(f'System: {"NTSC" if header.isNtsc else "PAL"}; clock: {header.clockFreq} Hz')
    print(f'SID: {", ".join(f"{model} @ ${address:04X}" for address, model in zip(header.sidAddresses, header.sidModels))}')
    print(f'Program payload: {len(payload)} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
