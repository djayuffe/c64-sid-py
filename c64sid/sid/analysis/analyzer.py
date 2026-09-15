"""Main SID analyzer - combines BPM, key, and pattern detection."""
from __future__ import annotations

from typing import Dict, Any, TYPE_CHECKING

from .bpm_detector import BPMDetector
from .key_detector import KeyDetector
from .pattern_finder import PatternFinder

if TYPE_CHECKING:
    from ..sidpro_forensic import SIDProForensicExport


class SIDAnalyzer:
    """Complete SID music analyzer."""

    @staticmethod
    def analyze_full(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Perform complete analysis on SID export."""

        # BPM detection
        bpm_result = BPMDetector.detect(export)

        # Key detection
        key_result = KeyDetector.detect(export)

        # Pattern analysis
        pattern_result = PatternFinder.analyze(export)

        # Combine results
        analysis = {
            'analyzed': True,
            'bpm': bpm_result.get('bpm'),
            'bpm_confidence': bpm_result.get('confidence', 0.0),
            'key': key_result.get('key'),
            'mode': key_result.get('mode'),
            'key_confidence': key_result.get('confidence', 0.0),
            'instruments': pattern_result.get('instruments', []),
            'loops': pattern_result.get('loops', []),
            'sections': pattern_result.get('sections', []),
            'detailed_results': {
                'bpm': bpm_result,
                'key': key_result,
                'patterns': pattern_result
            }
        }

        return analysis

    @staticmethod
    def analyze_and_update_export(export: 'SIDProForensicExport') -> None:
        """Analyze and update the export's analysis field."""
        analysis = SIDAnalyzer.analyze_full(export)
        export.analysis = analysis

    @staticmethod
    def get_summary(export: 'SIDProForensicExport') -> str:
        """Get human-readable analysis summary."""
        analysis = SIDAnalyzer.analyze_full(export)

        lines = []
        lines.append("=== SID Music Analysis ===")

        # BPM
        if analysis.get('bpm'):
            bpm = analysis['bpm']
            conf = analysis.get('bpm_confidence', 0) * 100
            lines.append(f"Tempo: {bpm:.1f} BPM (confidence: {conf:.0f}%)")
        else:
            lines.append("Tempo: Unable to detect")

        # Key
        if analysis.get('key'):
            key = analysis['key']
            mode = analysis.get('mode', 'unknown')
            conf = analysis.get('key_confidence', 0) * 100
            lines.append(f"Key: {key} {mode} (confidence: {conf:.0f}%)")
        else:
            lines.append("Key: Unable to detect")

        # Instruments
        instruments = analysis.get('instruments', [])
        if instruments:
            lines.append(f"\nInstruments: {len(instruments)} distinct patches")
            for idx, inst in enumerate(instruments[:3]):
                wave_names = {0: 'None', 1: 'Triangle', 2: 'Saw', 3: 'Tri+Saw',
                             4: 'Pulse', 8: 'Noise'}
                wave = wave_names.get(inst.get('wave', 0), f"Wave{inst.get('wave')}")
                count = inst.get('usage_count', 0)
                lines.append(f"  #{idx+1}: {wave} - used {count} times")

        # Structure
        loops = analysis.get('loops', [])
        if loops:
            lines.append(f"\nStructure: {len(loops)} loop(s) detected")
            for loop in loops[:2]:
                start = loop.get('start_frame', 0)
                length = loop.get('length_frames', 0)
                lines.append(f"  Loop at frame {start}, length {length}")

        sections = analysis.get('sections', [])
        if sections:
            lines.append(f"  {len(sections)} section(s): " +
                        ', '.join(s.get('type', 'unknown') for s in sections[:5]))

        return '\n'.join(lines)
