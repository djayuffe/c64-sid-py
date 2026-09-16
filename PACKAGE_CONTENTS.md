# Repository contents

The `c64sid` 0.3.0 source repository provides these supported surfaces:

| Area | Contents |
| --- | --- |
| Library | `c64sid.sid` playback, system, SID chip, parser, SID-PRO, analysis, and seeking modules |
| Waveforms | Bundled 6581/8580 combined-waveform measurement tables |
| CLI | `c64sid-render`, `c64sid-analyze`, `c64sid-visualize`, `c64sid-to-csv` |
| Live example | `examples/render_live_tone.py` renders a playable PCM WAV tone |
| Validation | `tests/` and `ruff check .` |

Install with `python3 -m pip install .`. See [README.md](README.md) for usage
and [SIDPRO_FORMAT.md](SIDPRO_FORMAT.md) for capture/export details.

The package requires Python 3.10+ and uses only standard-library runtime
dependencies.
