#!/usr/bin/env python3
"""Inspect PSID or RSID header metadata without rendering audio."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from c64sid import __version__
from c64sid.sid.sid_parser import parse_sid_header


def header_to_dict(header, payload_size: int) -> dict[str, object]:
    """Return stable, JSON-friendly metadata for a parsed SID header."""
    sid_chips = [
        {'address': f'${address:04X}', 'model': model}
        for address, model in zip(header.sidAddresses, header.sidModels)
    ]
    return {
        'format': header.magic,
        'version': header.version,
        'title': header.title,
        'author': header.author,
        'released': header.released,
        'songs': header.songs,
        'start_song': header.startSong,
        'load_address': f'${header.loadAddress:04X}',
        'init_address': f'${header.initAddress:04X}',
        'play_address': f'${header.playAddress:04X}',
        'standard': 'NTSC' if header.isNtsc else 'PAL',
        'clock_hz': header.clockFreq,
        'sid_chips': sid_chips,
        'payload_bytes': payload_size,
    }


def format_header(metadata: dict[str, object]) -> str:
    """Format inspected metadata for terminal output."""
    chips = metadata['sid_chips']
    chip_summary = ', '.join(f"{chip['model']} at {chip['address']}" for chip in chips)
    lines = [
        '=== SID file ===',
        f"Format: {metadata['format']} v{metadata['version']}",
        f"Title: {metadata['title'] or '(untitled)'}",
        f"Author: {metadata['author'] or '(unknown)'}",
        f"Released: {metadata['released'] or '(unknown)'}",
        f"Songs: {metadata['songs']} (default: {metadata['start_song']})",
        f"Load/init/play: {metadata['load_address']} / {metadata['init_address']} / {metadata['play_address']}",
        f"Video standard: {metadata['standard']} ({metadata['clock_hz']} Hz)",
        f"SID chips: {chip_summary}",
        f"Payload: {metadata['payload_bytes']} bytes",
    ]
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=f'c64sid {__version__}')
    parser.add_argument('input_sid', help='Input PSID or RSID file')
    parser.add_argument('--json', action='store_true', help='Print machine-readable JSON')
    args = parser.parse_args()

    try:
        header, payload = parse_sid_header(Path(args.input_sid).read_bytes())
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2

    metadata = header_to_dict(header, len(payload))
    if args.json:
        print(json.dumps(metadata, indent=2, sort_keys=True))
    else:
        print(format_header(metadata))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
