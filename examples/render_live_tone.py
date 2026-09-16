#!/usr/bin/env python3
"""Render a short, self-contained SID sawtooth tone to a WAV file."""
from __future__ import annotations

import argparse
import sys
import wave
from array import array
from pathlib import Path

from c64sid.sid.sid_chip import SidChip


PAL_CLOCK_HZ = 985_248


def render_tone(
    output_path: str | Path,
    *,
    seconds: float = 2.0,
    sample_rate: int = 44_100,
    frequency: float = 440.0,
    model: str = '6581',
) -> int:
    """Render a gated SID sawtooth tone and return the number of samples."""
    if seconds <= 0 or sample_rate <= 0 or frequency <= 0:
        raise ValueError('seconds, sample_rate, and frequency must be positive')
    if model not in ('6581', '8580'):
        raise ValueError('model must be 6581 or 8580')

    chip = SidChip(PAL_CLOCK_HZ)
    chip.set_model(model)
    sid_frequency = round(frequency * (1 << 24) / PAL_CLOCK_HZ)
    chip.write(0x00, sid_frequency & 0xFF)
    chip.write(0x01, sid_frequency >> 8)
    chip.write(0x05, 0x00)  # Fast attack and decay.
    chip.write(0x06, 0xF0)  # Full sustain and fast release.
    chip.write(0x18, 0x0F)  # Maximum master volume.
    chip.write(0x04, 0x21)  # Sawtooth + gate.

    sample_count = int(round(seconds * sample_rate))
    samples = array('h')
    cycle_fraction = 0.0
    for _ in range(sample_count):
        cycle_fraction += PAL_CLOCK_HZ / sample_rate
        cycles = int(cycle_fraction)
        cycle_fraction -= cycles
        chip.update(cycles)
        samples.append(int(round(chip.render_sample() * 32767.0)))

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(destination), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())
    return sample_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_wav', help='Output PCM WAV file')
    parser.add_argument('--seconds', type=float, default=2.0)
    parser.add_argument('--sample-rate', type=int, default=44_100)
    parser.add_argument('--frequency', type=float, default=440.0)
    parser.add_argument('--model', choices=('6581', '8580'), default='6581')
    args = parser.parse_args()
    samples = render_tone(
        args.output_wav,
        seconds=args.seconds,
        sample_rate=args.sample_rate,
        frequency=args.frequency,
        model=args.model,
    )
    print(f'Wrote {samples} samples to {args.output_wav}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
