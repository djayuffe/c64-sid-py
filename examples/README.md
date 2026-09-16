# Examples

## Live SID tone

Run this example from a source checkout:

```bash
python3 examples/render_live_tone.py live-tone.wav --seconds 2 --frequency 440
```

Choose either supported SID model or a different standard PCM sample rate:

```bash
python3 examples/render_live_tone.py live-8580.wav --model 8580 --frequency 220 --sample-rate 48000
```

The script creates a mono 16-bit PCM WAV through the maintained `SidChip`
renderer. It is intentionally self-contained: it does not need a SID file,
ROM image, or external dependency. The tone is a simple sawtooth
demonstration, not a hardware-reference test.

## Inspect a SID file

The parser example reads a PSID/RSID header without rendering audio:

```bash
python3 examples/inspect_sid.py music.sid
```

For a command-line report or JSON suitable for scripts, use the installed
equivalent:

```bash
c64sid-inspect music.sid
c64sid-inspect music.sid --json
```
