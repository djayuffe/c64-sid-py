#!/usr/bin/env python3
"""Visualize SID waveforms and envelopes from telemetry data."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from c64sid.sid.sidpro_forensic import SIDProForensicExport


def generate_ascii_waveform(data: list, width: int = 80, height: int = 20) -> str:
    """Generate ASCII art waveform."""
    if not data:
        return "No data"

    # Normalize data to 0-1
    min_val = min(data)
    max_val = max(data)
    range_val = max_val - min_val

    if range_val == 0:
        normalized = [0.5] * len(data)
    else:
        normalized = [(v - min_val) / range_val for v in data]

    # Sample data to fit width
    if len(data) > width:
        step = len(data) / width
        samples = [data[int(i * step)] for i in range(width)]
        normalized = [(v - min_val) / range_val if range_val > 0 else 0.5 for v in samples]
    else:
        samples = data

    # Build ASCII grid
    lines = []
    for row in range(height):
        line = []
        threshold = 1.0 - (row / height)

        for val in normalized:
            if val >= threshold:
                line.append('█')
            else:
                line.append(' ')

        lines.append(''.join(line))

    return '\n'.join(lines)


def visualize_envelope(export: SIDProForensicExport, chip: int = 0, voice: int = 0):
    """Visualize envelope for a specific voice."""
    frames = export.telemetry.get('frames', [])
    if not frames:
        print("No telemetry data")
        return

    env_values = []
    frame_numbers = []

    for frame in frames:
        chips = frame.get('chips', [])
        if chip >= len(chips):
            continue

        voices = chips[chip].get('voices', [])
        if voice >= len(voices):
            continue

        env = voices[voice].get('env', {})
        env_out = env.get('out', 0)

        env_values.append(env_out)
        frame_numbers.append(frame.get('frame', 0))

    if not env_values:
        print("No envelope data found")
        return

    print(f"\n=== Envelope - Chip {chip}, Voice {voice} ===")
    print(f"Frames: {len(env_values)}")
    print(f"Range: {min(env_values)} - {max(env_values)}")
    print()
    print(generate_ascii_waveform(env_values, width=80, height=15))
    print()


def visualize_frequency(export: SIDProForensicExport, chip: int = 0, voice: int = 0):
    """Visualize frequency changes for a specific voice."""
    frames = export.telemetry.get('frames', [])
    if not frames:
        print("No telemetry data")
        return

    freq_values = []

    for frame in frames:
        chips = frame.get('chips', [])
        if chip >= len(chips):
            continue

        voices = chips[chip].get('voices', [])
        if voice >= len(voices):
            continue

        derived = voices[voice].get('derived', {})
        freq_hz = derived.get('freq_hz', 0)

        freq_values.append(freq_hz)

    if not freq_values:
        print("No frequency data found")
        return

    print(f"\n=== Frequency - Chip {chip}, Voice {voice} ===")
    print(f"Frames: {len(freq_values)}")
    print(f"Range: {min(freq_values):.1f} - {max(freq_values):.1f} Hz")
    print()
    print(generate_ascii_waveform(freq_values, width=80, height=15))
    print()


def visualize_activity(export: SIDProForensicExport):
    """Visualize overall voice activity."""
    frames = export.telemetry.get('frames', [])
    if not frames:
        print("No telemetry data")
        return

    activity_levels = []

    for frame in frames:
        active_count = 0

        chips = frame.get('chips', [])
        for chip in chips:
            voices = chip.get('voices', [])
            for voice in voices:
                derived = voice.get('derived', {})
                if derived.get('gate'):
                    active_count += 1

        activity_levels.append(active_count)

    if not activity_levels:
        print("No activity data found")
        return

    print("\n=== Voice Activity ===")
    print(f"Frames: {len(activity_levels)}")
    print(f"Max active voices: {max(activity_levels)}")
    print()
    print(generate_ascii_waveform(activity_levels, width=80, height=10))
    print()


def main():
    parser = argparse.ArgumentParser(description='Visualize SID-PRO data')
    parser.add_argument('input_sidpro', help='Input .sidpro file')
    parser.add_argument('--envelope', action='store_true', help='Show envelope')
    parser.add_argument('--frequency', action='store_true', help='Show frequency')
    parser.add_argument('--activity', action='store_true', help='Show activity')
    parser.add_argument('--chip', type=int, default=0, help='Chip index (default: 0)')
    parser.add_argument('--voice', type=int, default=0, help='Voice index (default: 0)')
    parser.add_argument('--all', action='store_true', help='Show all visualizations')
    args = parser.parse_args()

    if not any([args.envelope, args.frequency, args.activity, args.all]):
        args.all = True

    print(f"Loading {args.input_sidpro}...")
    export = SIDProForensicExport.load_from_file(args.input_sidpro)

    stats = export.get_statistics()
    print(f"Loaded: {stats['telemetry_frames']} frames, {stats['bus_events']} bus events")

    if args.all or args.activity:
        visualize_activity(export)

    if args.all or args.envelope:
        visualize_envelope(export, args.chip, args.voice)

    if args.all or args.frequency:
        visualize_frequency(export, args.chip, args.voice)


if __name__ == '__main__':
    main()
