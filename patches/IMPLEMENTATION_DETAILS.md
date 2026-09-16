# Experimental component notes

The `patches` directory contains independent, inspectable experiments:

- `combined_waveforms.py`: combined-waveform tables with packaged reSID data.
- `adsr_enhanced.py`: alternate ADSR state-machine experiment.
- `sid_filter_enhanced.py`: alternate filter experiment.
- `cia_timer_enhanced.py` and `vic_dma_enhanced.py`: isolated timing models.
- `deterministic_components.py`: fixed-point and state-helper experiments.

`integration.py` deliberately does not combine those isolated models into a
full C64. It configures maintained `SidChip` instances with the options that
the core renderer consumes: model, combined waveforms, ADSR pipeline, and noise
seed. This avoids presenting disconnected helper state as rendered audio.

Use `c64sid.sid.c64_system.C64System` and `PlaybackCoordinator` for the main
execution path. Any new integration of an experimental component must include
an end-to-end regression test and must not claim hardware validation without an
independent reference corpus.
