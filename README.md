# c64sid 0.3.4

Python tools for rendering PSID/RSID files, capturing SID-PRO
forensic data, and inspecting that data. The project is deterministic where
practical, but it is not a cycle-exact or analog-perfect C64/SID emulator.

## Features

| Need | Supported command or API |
| --- | --- |
| Inspect a PSID/RSID file | `c64sid-inspect music.sid` |
| Render a selected subsong to WAV | `c64sid-render music.sid output.wav --song 2` |
| Capture emulator telemetry | `c64sid-render ... --dump-sidpro capture.sidpro` |
| Analyze or visualize a capture | `c64sid-analyze`, `c64sid-visualize` |
| Export capture data | `c64sid-to-csv capture.sidpro --all` |

## Requirements and installation

- Python 3.10 or newer
- No runtime dependencies beyond the standard library

Install from this checkout:

```bash
python3 -m pip install .
```

The install provides `c64sid-inspect`, `c64sid-render`, `c64sid-analyze`,
`c64sid-visualize`, and `c64sid-to-csv`. The same commands can be run from a
source checkout with `python3 sid_render.py` and `python3 tools/<tool>.py`.

## Quick start

Inspect the file first to see its format, metadata, SID model, and valid
subsong range:

```bash
c64sid-inspect music.sid
c64sid-inspect music.sid --json
```

The human-readable report includes title, author, version, default subsong,
load/init/play addresses, video standard, SID chip models, and payload size.

## Render and capture

Render a SID file to WAV:

```bash
c64sid-render music.sid output.wav --seconds 30
```

Render a particular one-based subsong and choose the output rate:

```bash
c64sid-render music.sid output.wav --song 2 --seconds 90 --rate 48000
```

`--song` must be within the tune's declared range. The renderer accepts a
finite positive duration and a sample rate from 8,000 through 96,000 Hz.

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

The CSV tool derives its analysis report from telemetry when a capture does
not already contain persisted analysis data.

## Command reference

| Command | Input | Primary output |
| --- | --- | --- |
| `c64sid-inspect` | PSID/RSID | Header report or JSON metadata |
| `c64sid-render` | PSID/RSID | Mono 16-bit PCM WAV; optional `.sidpro` capture |
| `c64sid-analyze` | `.sidpro` | Terminal summary or analysis JSON |
| `c64sid-visualize` | `.sidpro` | ASCII envelope, frequency, and activity views |
| `c64sid-to-csv` | `.sidpro` | Bus-event, telemetry, and analysis CSV files |

All CLI commands support `--help`; installed builds also report their release
with `--version` where applicable.

## Python API

```python
from c64sid.sid.playback import PlaybackCoordinator

player = PlaybackCoordinator()
player.enable_sidpro_export('capture.sidpro')
player.load_sid_bytes(sid_bytes, song=2)
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
path. A parser API example is also included:

```bash
python3 examples/inspect_sid.py music.sid
```

See [examples/README.md](examples/README.md) for details.

Use `c64sid-render --help` to see input, ROM, telemetry, and output options,
or `c64sid-render --version` to identify the installed build.

## Project layout

- `c64sid/`: maintained emulation, playback, SID-PRO, and analysis code.
- `tools/`: installed and source-checkout command-line utilities.
- `tests/`: regression coverage for parsing, playback helpers, export, seeking,
  waveform resources, analysis, and package behavior.
- `examples/`: runnable tone rendering and SID inspection examples using
  maintained APIs.
- `SIDPRO_FORMAT.md`: the supported SID-PRO JSON and binary interfaces.

## Limitations

The renderer has simplified analog SID/filter behavior. Analysis results are
heuristic, and forensic data represents this implementation's bus and telemetry
state—not a claim of real-hardware reconstruction. Validate output against the
emulator or hardware appropriate to your use case.

## Project status

This is a public Python toolkit with a standard-library-only runtime. Its SID
models and analysis are useful for experimentation, inspection, and offline
rendering; they are not a substitute for hardware verification or a
cycle-exact emulator.

## License

No distribution license has been selected. Treat this private source as
all-rights-reserved unless the repository owner grants other permission.
