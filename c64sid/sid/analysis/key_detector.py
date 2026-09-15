"""Musical key detection for SID music."""
from __future__ import annotations

import math
from typing import Dict, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..sidpro_forensic import SIDProForensicExport


class KeyDetector:
    """Detect musical key from SID frequency data."""

    # Note frequencies (A440 tuning) for one octave
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    # Major and minor key profiles (Krumhansl-Kessler)
    MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

    @staticmethod
    def freq_to_note(freq_hz: float) -> int:
        """Convert frequency to MIDI note number."""
        if freq_hz <= 0:
            return -1
        # MIDI note = 12 * log2(f / 440) + 69
        note = 12 * math.log2(freq_hz / 440.0) + 69
        return round(note)

    @staticmethod
    def note_to_chroma(note: int) -> int:
        """Convert MIDI note to chroma (0-11, C=0)."""
        return note % 12

    @staticmethod
    def analyze_pitch_histogram(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Build pitch class histogram from telemetry."""
        frames = export.telemetry.get('frames', [])
        if not frames:
            return {'key': None, 'mode': None, 'confidence': 0.0}

        # Count pitch classes weighted by duration
        chroma_counts = [0.0] * 12
        total_weight = 0.0

        for frame in frames:
            chips = frame.get('chips', [])
            for chip in chips:
                voices = chip.get('voices', [])
                for voice in voices:
                    derived = voice.get('derived', {})

                    # Only count when gate is on
                    if not derived.get('gate', False):
                        continue

                    freq_hz = derived.get('freq_hz', 0)
                    if freq_hz < 20 or freq_hz > 20000:
                        continue

                    note = KeyDetector.freq_to_note(freq_hz)
                    if note < 0:
                        continue

                    chroma = KeyDetector.note_to_chroma(note)

                    # Weight by envelope level
                    env_data = voice.get('env', {})
                    env_level = env_data.get('out', 0) / 255.0

                    chroma_counts[chroma] += env_level
                    total_weight += env_level

        if total_weight == 0:
            return {'key': None, 'mode': None, 'confidence': 0.0}

        # Normalize
        chroma_profile = [c / total_weight for c in chroma_counts]

        # Find best key match using correlation
        best_key = None
        best_mode = None
        best_corr = -1.0

        for tonic in range(12):
            # Test major
            rotated_major = KeyDetector.MAJOR_PROFILE[tonic:] + KeyDetector.MAJOR_PROFILE[:tonic]
            corr_major = KeyDetector.correlate(chroma_profile, rotated_major)

            if corr_major > best_corr:
                best_corr = corr_major
                best_key = tonic
                best_mode = 'major'

            # Test minor
            rotated_minor = KeyDetector.MINOR_PROFILE[tonic:] + KeyDetector.MINOR_PROFILE[:tonic]
            corr_minor = KeyDetector.correlate(chroma_profile, rotated_minor)

            if corr_minor > best_corr:
                best_corr = corr_minor
                best_key = tonic
                best_mode = 'minor'

        if best_key is None:
            return {'key': None, 'mode': None, 'confidence': 0.0}

        key_name = KeyDetector.NOTE_NAMES[best_key]

        return {
            'key': key_name,
            'mode': best_mode,
            'confidence': round(max(0.0, min(1.0, best_corr)), 3),
            'chroma_profile': [round(c, 3) for c in chroma_profile],
            'tonic_chroma': best_key
        }

    @staticmethod
    def correlate(profile_a: List[float], profile_b: List[float]) -> float:
        """Calculate correlation between two profiles."""
        if len(profile_a) != len(profile_b):
            return 0.0

        # Pearson correlation
        n = len(profile_a)
        mean_a = sum(profile_a) / n
        mean_b = sum(profile_b) / n

        num = sum((profile_a[i] - mean_a) * (profile_b[i] - mean_b) for i in range(n))

        var_a = sum((profile_a[i] - mean_a) ** 2 for i in range(n))
        var_b = sum((profile_b[i] - mean_b) ** 2 for i in range(n))

        denom = math.sqrt(var_a * var_b)

        if denom == 0:
            return 0.0

        return num / denom

    @staticmethod
    def detect(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Main key detection method."""
        return KeyDetector.analyze_pitch_histogram(export)
