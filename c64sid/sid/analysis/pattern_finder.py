"""Pattern detection and structure analysis for SID music."""
from __future__ import annotations

import hashlib
from typing import Dict, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..sidpro_forensic import SIDProForensicExport


class PatternFinder:
    """Detect repeating patterns and musical structure."""

    @staticmethod
    def extract_voice_signature(voice_data: Dict[str, Any]) -> str:
        """Create a signature for a voice state."""
        derived = voice_data.get('derived', {})
        regs = voice_data.get('reg', {})

        # Quantize frequency to reduce noise
        freq = regs.get('freq', 0)
        freq_bucket = freq // 100  # Group by ~100 Hz

        gate = 1 if derived.get('gate') else 0
        wave = derived.get('wave', 0)

        return f"{gate}:{wave}:{freq_bucket}"

    @staticmethod
    def extract_frame_signature(frame: Dict[str, Any]) -> str:
        """Create a signature for an entire frame."""
        chips = frame.get('chips', [])
        signatures = []

        for chip in chips:
            voices = chip.get('voices', [])
            for voice in voices:
                sig = PatternFinder.extract_voice_signature(voice)
                signatures.append(sig)

        return '|'.join(signatures)

    @staticmethod
    def find_loops(export: 'SIDProForensicExport',
                   min_length: int = 10,
                   max_search: int = 1000) -> List[Dict[str, Any]]:
        """Find repeating sections (loops) in the music."""
        frames = export.telemetry.get('frames', [])
        if len(frames) < min_length * 2:
            return []

        # Extract signatures for each frame
        signatures = [PatternFinder.extract_frame_signature(f) for f in frames[:max_search]]

        loops = []

        # Search for repeating patterns
        for start in range(len(signatures) - min_length):
            for length in range(min_length, min(100, len(signatures) - start)):
                pattern = signatures[start:start + length]

                # Look for repetition
                for match_start in range(start + length, len(signatures) - length):
                    if signatures[match_start:match_start + length] == pattern:
                        loops.append({
                            'start_frame': start,
                            'length_frames': length,
                            'repeat_at_frame': match_start,
                            'pattern_hash': hashlib.sha256(
                                '\x1f'.join(pattern).encode('utf-8')
                            ).hexdigest(),
                        })
                        break

        # Deduplicate and sort by length
        unique_loops = {}
        for loop in loops:
            key = (loop['start_frame'], loop['length_frames'])
            if key not in unique_loops:
                unique_loops[key] = loop

        result = sorted(unique_loops.values(),
                       key=lambda x: x['length_frames'],
                       reverse=True)

        return result[:10]  # Return top 10

    @staticmethod
    def detect_sections(export: 'SIDProForensicExport') -> List[Dict[str, Any]]:
        """Detect structural sections (intro, verse, chorus, etc.)."""
        frames = export.telemetry.get('frames', [])
        if not frames:
            return []

        # Analyze activity level per frame
        activity_levels = []

        for frame in frames:
            active_voices = 0
            total_freq = 0.0

            chips = frame.get('chips', [])
            for chip in chips:
                voices = chip.get('voices', [])
                for voice in voices:
                    derived = voice.get('derived', {})
                    if derived.get('gate'):
                        active_voices += 1
                        total_freq += derived.get('freq_hz', 0)

            activity_levels.append({
                'frame': frame.get('frame', 0),
                'active_voices': active_voices,
                'avg_freq': total_freq / max(1, active_voices)
            })

        # Detect sections by activity changes
        sections = []
        current_section = {
            'start_frame': 0,
            'type': 'intro',
            'avg_activity': 0.0
        }

        window_size = 20
        for i in range(0, len(activity_levels), window_size):
            window = activity_levels[i:i + window_size]
            avg_activity = sum(w['active_voices'] for w in window) / len(window)

            # Detect change
            if abs(avg_activity - current_section['avg_activity']) > 0.5:
                if i > 0:
                    current_section['end_frame'] = i
                    sections.append(current_section)

                # Start new section
                section_type = 'section'
                if avg_activity < 1.0:
                    section_type = 'break'
                elif avg_activity > 2.5:
                    section_type = 'chorus'
                else:
                    section_type = 'verse'

                current_section = {
                    'start_frame': i,
                    'type': section_type,
                    'avg_activity': avg_activity
                }

        # Close last section
        if current_section:
            current_section['end_frame'] = len(activity_levels)
            sections.append(current_section)

        return sections

    @staticmethod
    def identify_instruments(export: 'SIDProForensicExport') -> List[Dict[str, Any]]:
        """Identify distinct instruments/patches used."""
        frames = export.telemetry.get('frames', [])
        if not frames:
            return []

        # Track unique register combinations
        instruments = {}

        for frame in frames:
            chips = frame.get('chips', [])
            for chip in chips:
                voices = chip.get('voices', [])
                for voice_idx, voice in enumerate(voices):
                    derived = voice.get('derived', {})
                    regs = voice.get('reg', {})

                    if not derived.get('gate'):
                        continue

                    # Create instrument signature from ADSR + waveform
                    wave = derived.get('wave', 0)
                    ad = regs.get('ad', 0)
                    sr = regs.get('sr', 0)

                    sig = (wave, ad, sr)

                    if sig not in instruments:
                        instruments[sig] = {
                            'wave': wave,
                            'attack': (ad >> 4) & 0x0F,
                            'decay': ad & 0x0F,
                            'sustain': (sr >> 4) & 0x0F,
                            'release': sr & 0x0F,
                            'usage_count': 0,
                            'voices_used': set()
                        }

                    instruments[sig]['usage_count'] += 1
                    instruments[sig]['voices_used'].add(voice_idx)

        # Convert to list and sort by usage
        result = []
        for idx, (sig, data) in enumerate(instruments.items()):
            data['instrument_id'] = idx
            data['voices_used'] = list(data['voices_used'])
            result.append(data)

        result.sort(key=lambda x: x['usage_count'], reverse=True)

        return result

    @staticmethod
    def analyze(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Full pattern analysis."""
        return {
            'loops': PatternFinder.find_loops(export),
            'sections': PatternFinder.detect_sections(export),
            'instruments': PatternFinder.identify_instruments(export)
        }
