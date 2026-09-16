# c64sid 0.3.0

Python tools for rendering PSID/RSID files, capturing SID-PRO
forensic data, and inspecting that data. The project is deterministic where
practical, but it is not a cycle-exact or analog-perfect C64/SID emulator.

## Requirements and installation

- Python 3.10 or newer
- No runtime dependencies beyond the standard library

Install from this checkout:

```bash
python3 -m pip install .
```

The install provides `c64sid-render`, `c64sid-analyze`, `c64sid-visualize`,
and `c64sid-to-csv`. The same commands can be run from a
source checkout with `python3 sid_render.py` and `python3 tools/<tool>.py`.

## Usage

Render a SID file to WAV:

```bash
c64sid-render music.sid output.wav --seconds 30
```

Capture SID-PRO JSON alongside the WAV:

```bash
c64sid-render music.sid output.wav --seconds 30 --dump-sidpro capture.sidpro
```

Analyze, visualize, or export a capture:

```bash
c64sid-analyze capture.sidpro --detailed
c64sid-visualize capture.sidpro --envelope --voice 0
c64sid-to-csv capture.sidpro --all --output-prefix capture
```

## Python API

```python
from c64sid.sid.playback import PlaybackCoordinator

player = PlaybackCoordinator()
player.enable_sidpro_export('capture.sidpro')
player.load_sid_bytes(sid_bytes)
result = player.render_to_wav('output.wav', seconds=30)
print(result.samples)
```

## Validation

```bash
python3 -m unittest discover -v
ruff check .
```

These are regression and static checks; they are not hardware-conformance
benchmarks.

## Live example

Render a self-contained SID sawtooth demonstration:

```bash
python3 examples/render_live_tone.py live-tone.wav --seconds 2 --frequency 440
```

The command creates a standard mono PCM WAV using the maintained `SidChip`
path. See [examples/README.md](examples/README.md) for details.

## Project layout

- `c64sid/`: maintained emulation, playback, SID-PRO, and analysis code.
- `tools/`: installed and source-checkout command-line utilities.
- `tests/`: regression coverage for parsing, playback helpers, export, seeking,
  waveform resources, analysis, and package behavior.
- `examples/`: small runnable examples using maintained APIs.
- `SIDPRO_FORMAT.md`: the supported SID-PRO JSON and binary interfaces.

## Limitations

The renderer has simplified analog SID/filter behavior. Analysis results are
heuristic, and forensic data represents this implementation's bus and telemetry
state—not a claim of real-hardware reconstruction. Validate output against the
emulator or hardware appropriate to your use case.

## License

No distribution license has been selected. Treat this private source as
all-rights-reserved unless the repository owner grants other permission.
