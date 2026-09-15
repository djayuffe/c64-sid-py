#!/usr/bin/env python3
"""Export SID-PRO forensic data to CSV format."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from c64sid.sid.sidpro_forensic import SIDProForensicExport


def export_bus_events_csv(export: SIDProForensicExport, output_path: str):
    """Export bus events to CSV."""
    import struct

    cycles_raw = export._bus_cycles_raw
    events_raw = export._bus_events_raw
    if not cycles_raw or not events_raw:
        print("No bus events in export")
        return
    if len(cycles_raw) % 8 or len(events_raw) % 3:
        raise ValueError('Invalid SID-PRO bus stream lengths')
    num_events = len(cycles_raw) // 8
    if num_events != len(events_raw) // 3:
        raise ValueError('SID-PRO bus cycle/event counts differ')
    cycles = struct.unpack(f'<{num_events}d', cycles_raw)

    # Write CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Cycle', 'Chip', 'Register', 'Value', 'Register_Hex', 'Value_Hex'])

        for i in range(num_events):
            cycle = cycles[i]
            chip = events_raw[i * 3]
            reg = events_raw[i * 3 + 1]
            val = events_raw[i * 3 + 2]

            writer.writerow([
                f"{cycle:.0f}",
                chip,
                reg,
                val,
                f"${reg:02X}",
                f"${val:02X}"
            ])

    print(f"Wrote {num_events} bus events to {output_path}")


def export_telemetry_csv(export: SIDProForensicExport, output_path: str):
    """Export telemetry frames to CSV."""
    frames = export.telemetry.get('frames', [])

    if not frames:
        print("No telemetry frames in export")
        return

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header
        header = ['Frame', 'Cycle']
        for chip_idx in range(3):  # Assume max 3 chips
            for voice_idx in range(3):
                prefix = f"C{chip_idx}V{voice_idx}"
                header.extend([
                    f"{prefix}_Gate",
                    f"{prefix}_Freq",
                    f"{prefix}_Wave",
                    f"{prefix}_Env",
                    f"{prefix}_Phase"
                ])
        writer.writerow(header)

        # Data
        for frame in frames:
            row = [frame.get('frame', 0), frame.get('cycle', 0)]

            chips = frame.get('chips', [])
            for chip_idx in range(3):
                chip = chips[chip_idx] if chip_idx < len(chips) else {}
                voices = chip.get('voices', [])
                for voice_idx in range(3):
                    voice = voices[voice_idx] if voice_idx < len(voices) else {}
                    derived = voice.get('derived', {})
                    regs = voice.get('reg', {})
                    env = voice.get('env', {})
                    osc = voice.get('osc', {})

                    row.extend([
                        1 if derived.get('gate') else 0,
                        regs.get('freq', 0),
                        derived.get('wave', 0),
                        env.get('out', 0),
                        osc.get('acc', 0)
                    ])

            writer.writerow(row)

    print(f"Wrote {len(frames)} telemetry frames to {output_path}")


def export_analysis_csv(export: SIDProForensicExport, output_path: str):
    """Export analysis results to CSV."""
    analysis = export.analysis

    if not analysis:
        print("No analysis data in export")
        return

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Property', 'Value'])

        writer.writerow(['BPM', analysis.get('bpm', 'N/A')])
        writer.writerow(['Key', analysis.get('key', 'N/A')])
        writer.writerow(['Mode', analysis.get('mode', 'N/A')])

        instruments = analysis.get('instruments', [])
        writer.writerow(['Instruments', len(instruments)])

        loops = analysis.get('loops', [])
        writer.writerow(['Loops', len(loops)])

        sections = analysis.get('sections', [])
        writer.writerow(['Sections', len(sections)])

    print(f"Wrote analysis to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Export SID-PRO to CSV')
    parser.add_argument('input_sidpro', help='Input .sidpro file')
    parser.add_argument('--output-prefix', default='export', help='Output file prefix')
    parser.add_argument('--bus-events', action='store_true', help='Export bus events')
    parser.add_argument('--telemetry', action='store_true', help='Export telemetry')
    parser.add_argument('--analysis', action='store_true', help='Export analysis')
    parser.add_argument('--all', action='store_true', help='Export all data')
    args = parser.parse_args()

    if not any([args.bus_events, args.telemetry, args.analysis, args.all]):
        args.all = True

    print(f"Loading {args.input_sidpro}...")
    export = SIDProForensicExport.load_from_file(args.input_sidpro)

    if args.all or args.bus_events:
        output = f"{args.output_prefix}_bus_events.csv"
        print(f"\nExporting bus events to {output}...")
        export_bus_events_csv(export, output)

    if args.all or args.telemetry:
        output = f"{args.output_prefix}_telemetry.csv"
        print(f"\nExporting telemetry to {output}...")
        export_telemetry_csv(export, output)

    if args.all or args.analysis:
        output = f"{args.output_prefix}_analysis.csv"
        print(f"\nExporting analysis to {output}...")
        export_analysis_csv(export, output)

    print("\nDone!")


if __name__ == '__main__':
    main()
