# Live SID tone

Run this example from a source checkout:

```bash
python3 examples/render_live_tone.py live-tone.wav --seconds 2 --frequency 440
```

It creates a mono 16-bit PCM WAV through the maintained `SidChip` renderer.
The tone is a simple sawtooth demonstration, not a hardware-reference test.
