"""BPM detection for SID music using onset detection and autocorrelation."""
from __future__ import annotations

import math
from typing import Dict, List, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..sidpro_forensic import SIDProForensicExport


class BPMDetector:
    """Detect tempo (BPM) from SID telemetry data."""

    @staticmethod
    def detect_from_gate_events(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Detect BPM by analyzing note gate events."""
        frames = export.telemetry.get('frames', [])
        if not frames:
            return {'bpm': None, 'confidence': 0.0, 'method': 'none'}

        config = export.metadata.get('config', {})
        clock_hz = config.get('clock_hz', 985248)
        # Collect rising gate edges for each voice.  Sampling every frame where
        # a note remains gated would measure the telemetry rate, not note onsets.
        gate_events: List[float] = []
        previous_gates: Dict[tuple[int, int], bool] = {}

        for frame in frames:
            cycle = frame.get('cycle', 0)
            time_sec = cycle / clock_hz

            chips = frame.get('chips', [])
            for chip_idx, chip in enumerate(chips):
                voices = chip.get('voices', [])
                for voice_idx, voice in enumerate(voices):
                    derived = voice.get('derived', {})
                    key = (chip_idx, voice_idx)
                    gate = bool(derived.get('gate'))
                    if gate and not previous_gates.get(key, False):
                        gate_events.append(time_sec)
                    previous_gates[key] = gate

        if len(gate_events) < 10:
            return {'bpm': None, 'confidence': 0.0, 'method': 'gate_events'}

        # Calculate inter-onset intervals
        intervals = []
        for i in range(1, len(gate_events)):
            interval = gate_events[i] - gate_events[i-1]
            if 0.1 < interval < 5.0:  # Filter outliers
                intervals.append(interval)

        if not intervals:
            return {'bpm': None, 'confidence': 0.0, 'method': 'gate_events'}

        # Find most common interval using histogram
        intervals.sort()
        median_interval = intervals[len(intervals) // 2]

        # BPM from interval
        bpm = 60.0 / median_interval if median_interval > 0 else None

        # Calculate confidence based on interval consistency
        avg_interval = sum(intervals) / len(intervals)
        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = math.sqrt(variance)
        confidence = max(0.0, 1.0 - (std_dev / avg_interval))

        return {
            'bpm': round(bpm, 1) if bpm else None,
            'confidence': round(confidence, 3),
            'method': 'gate_events',
            'intervals_analyzed': len(intervals),
            'median_interval': round(median_interval, 3)
        }

    @staticmethod
    def detect_from_play_calls(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Detect BPM from play routine call frequency."""
        # Most SID tunes call play() at 50Hz (PAL) or 60Hz (NTSC)
        # BPM can be inferred if play() triggers notes at regular intervals

        # Common patterns:
        # - 50 Hz / 1 = 50 updates/sec -> 3000/min
        # - Notes every 2 frames = 25 Hz -> BPM ~150
        # - Notes every 4 frames = 12.5 Hz -> BPM ~75

        return {
            'bpm': None,
            'confidence': 0.0,
            'method': 'play_calls',
            'note': 'Requires runtime analysis'
        }

    @staticmethod
    def autocorrelation_bpm(values: List[float], sample_rate: float) -> Dict[str, Any]:
        """Use autocorrelation to find periodic patterns."""
        if len(values) < 100:
            return {'bpm': None, 'confidence': 0.0}

        # Simple autocorrelation
        n = len(values)
        mean = sum(values) / n

        # Normalize
        normalized = [v - mean for v in values]

        # Calculate autocorrelation for lags
        max_lag = min(n // 2, int(sample_rate * 3))  # Up to 3 seconds
        correlations = []

        for lag in range(1, max_lag):
            corr = sum(normalized[i] * normalized[i + lag]
                      for i in range(n - lag))
            correlations.append((lag, corr))

        # Find peaks
        if not correlations:
            return {'bpm': None, 'confidence': 0.0}

        # Get strongest correlation
        correlations.sort(key=lambda x: x[1], reverse=True)
        best_lag, best_corr = correlations[0]

        # Convert lag to BPM
        interval_sec = best_lag / sample_rate
        bpm = 60.0 / interval_sec if interval_sec > 0 else None

        # Normalize confidence
        max_corr = max(abs(c[1]) for c in correlations[:10])
        confidence = abs(best_corr) / max_corr if max_corr > 0 else 0.0

        return {
            'bpm': round(bpm, 1) if bpm and 40 < bpm < 300 else None,
            'confidence': round(confidence, 3),
            'method': 'autocorrelation',
            'lag_samples': best_lag
        }

    @staticmethod
    def detect(export: 'SIDProForensicExport') -> Dict[str, Any]:
        """Main BPM detection method - tries multiple approaches."""
        gate_result = BPMDetector.detect_from_gate_events(export)

        # Could combine with other methods
        results = [gate_result]

        # Return highest confidence result
        best = max(results, key=lambda x: x.get('confidence', 0))

        return {
            'bpm': best.get('bpm'),
            'confidence': best.get('confidence', 0.0),
            'method': best.get('method', 'unknown'),
            'all_results': results
        }
