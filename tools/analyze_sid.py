#!/usr/bin/env python3
"""Analyze SID music from SID-PRO forensic export."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from c64sid.sid.sidpro_forensic import SIDProForensicExport
from c64sid.sid.analysis import SIDAnalyzer


def main():
    parser = argparse.ArgumentParser(description='Analyze SID music')
    parser.add_argument('input_sidpro', help='Input .sidpro file')
    parser.add_argument('--output-json', help='Save analysis as JSON')
    parser.add_argument('--summary', action='store_true', help='Show text summary')
    parser.add_argument('--detailed', action='store_true', help='Show detailed results')
    args = parser.parse_args()

    print(f"Loading {args.input_sidpro}...")
    export = SIDProForensicExport.load_from_file(args.input_sidpro)

    print("Analyzing...")
    analysis = SIDAnalyzer.analyze_full(export)

    if args.summary or not args.output_json:
        print()
        summary = SIDAnalyzer.get_summary(export)
        print(summary)
        print()

    if args.detailed:
        print("\n=== Detailed Results ===\n")

        # BPM
        bpm_details = analysis['detailed_results']['bpm']
        print(f"BPM Detection:")
        print(f"  Method: {bpm_details.get('method', 'unknown')}")
        print(f"  BPM: {bpm_details.get('bpm', 'N/A')}")
        print(f"  Confidence: {bpm_details.get('confidence', 0) * 100:.1f}%")
        if 'intervals_analyzed' in bpm_details:
            print(f"  Intervals: {bpm_details['intervals_analyzed']}")
        print()

        # Key
        key_details = analysis['detailed_results']['key']
        print(f"Key Detection:")
        print(f"  Key: {key_details.get('key', 'N/A')} {key_details.get('mode', '')}")
        print(f"  Confidence: {key_details.get('confidence', 0) * 100:.1f}%")
        if 'chroma_profile' in key_details:
            profile = key_details['chroma_profile']
            notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            print(f"  Pitch class distribution:")
            for i, val in enumerate(profile):
                if val > 0.01:
                    print(f"    {notes[i]}: {val:.3f}")
        print()

        # Patterns
        pattern_details = analysis['detailed_results']['patterns']

        instruments = pattern_details.get('instruments', [])
        print(f"Instruments ({len(instruments)}):")
        wave_names = {0: 'None', 1: 'Triangle', 2: 'Saw', 3: 'Tri+Saw',
                     4: 'Pulse', 8: 'Noise', 0x10: 'Triangle',
                     0x20: 'Saw', 0x40: 'Pulse', 0x80: 'Noise'}
        for inst in instruments[:10]:
            wave = wave_names.get(inst.get('wave', 0), f"0x{inst.get('wave', 0):02X}")
            a = inst.get('attack', 0)
            d = inst.get('decay', 0)
            s = inst.get('sustain', 0)
            r = inst.get('release', 0)
            count = inst.get('usage_count', 0)
            print(f"  {wave:12} ADSR:{a:X}{d:X}/{s:X}{r:X} - {count} uses")
        print()

        loops = pattern_details.get('loops', [])
        if loops:
            print(f"Loops ({len(loops)}):")
            for loop in loops[:5]:
                start = loop.get('start_frame', 0)
                length = loop.get('length_frames', 0)
                repeat = loop.get('repeat_at_frame', 0)
                print(f"  Frame {start} (length {length}) repeats at {repeat}")
            print()

        sections = pattern_details.get('sections', [])
        if sections:
            print(f"Sections ({len(sections)}):")
            for sec in sections:
                start = sec.get('start_frame', 0)
                end = sec.get('end_frame', 0)
                sec_type = sec.get('type', 'unknown')
                activity = sec.get('avg_activity', 0)
                print(f"  {start:5d} - {end:5d}: {sec_type:10} (activity: {activity:.1f})")
            print()

    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(analysis, f, indent=2)
        print(f"Saved analysis to {args.output_json}")


if __name__ == '__main__':
    main()
