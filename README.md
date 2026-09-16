# c64sid 0.2.0

Experimental Python tools for rendering PSID/RSID files, capturing SID-PRO
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
`c64sid-to-csv`, and `c64sid-to-vgm`. The same commands can be run from a
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

Standard VGM has no SID-chip command. `c64sid-to-vgm` deliberately refuses to
write an invalid conversion; use CSV or keep the SID-PRO data instead.

## Python API

```python
from c64sid.sid.playback import PlaybackCoordinator

player = PlaybackCoordinator()
player.enable_sidpro_export('capture.sidpro')
player.load_sid_bytes(sid_bytes)
result = player.render_to_wav('output.wav', seconds=30)
print(result.samples)
```

The small `patches` wrapper is a SID-only register-model helper. Its public
settings directly control its managed SID chips; it does not emulate CPU, CIA,
or VIC interaction. Use `PlaybackCoordinator` for full C64 playback.

```python
from patches import create_enhanced_emulator

sid = create_enhanced_emulator(
    model='6581', combined_waveforms=True, adsr_pipeline=True,
)
sid.write_register(0x04, 0x21)
sid.step(1000)
sample = sid.get_sample()
```

## Validation

```bash
python3 -m unittest discover -v
python3 verify_fixes.py
python3 patches/verify_installation.py
```

The first two commands are regression checks. The last command is a
deterministic component smoke check, not a hardware-conformance benchmark.

## Project layout

- `c64sid/`: maintained emulation, playback, SID-PRO, and analysis code.
- `patches/`: optional SID-only wrapper and experimental standalone helpers.
- `tools/`: installed and source-checkout command-line utilities.
- `tests/`: regression coverage for parsing, playback helpers, export, seeking,
  waveform resources, analysis, and package behavior.
- `SIDPRO_FORMAT.md`: the supported SID-PRO JSON and binary interfaces.

## Limitations

The renderer has simplified analog SID/filter behavior. Analysis results are
heuristic, and forensic data represents this implementation's bus and telemetry
state—not a claim of real-hardware reconstruction. Validate output against the
emulator or hardware appropriate to your use case.

## License

No distribution license has been selected. Treat this private source as
all-rights-reserved unless the repository owner grants other permission.
