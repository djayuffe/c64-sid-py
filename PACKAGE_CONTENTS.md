# Package contents

`c64sid` 0.2.0 ships these supported surfaces:

| Area | Contents |
| --- | --- |
| Library | `c64sid.sid` playback, system, SID chip, parser, SID-PRO, analysis, and seeking modules |
| Waveforms | Bundled 6581/8580 combined-waveform measurement tables |
| CLI | `c64sid-render`, `c64sid-analyze`, `c64sid-visualize`, `c64sid-to-csv`, `c64sid-to-vgm` |
| Experimental | `patches` SID-only wrapper and standalone helper components |
| Validation | `tests/`, `verify_fixes.py`, and `patches/verify_installation.py` |

Install with `python3 -m pip install .`. See [README.md](README.md) for usage
and [SIDPRO_FORMAT.md](SIDPRO_FORMAT.md) for capture/export details.

The package requires Python 3.10+ and uses only standard-library runtime
dependencies.
