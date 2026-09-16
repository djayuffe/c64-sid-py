# Experimental SID components

`patches` contains experimental standalone helpers plus a small SID-only
wrapper. They are useful for controlled experiments, but are not a complete C64
emulator and do not establish hardware or cycle accuracy.

```python
from patches import create_enhanced_emulator

emulator = create_enhanced_emulator(
    model='6581', combined_waveforms=True, adsr_pipeline=True,
)
emulator.write_register(0x04, 0x21)
emulator.step(1000)
print(emulator.get_sample())
```

The wrapper's model, combined-waveform, ADSR-pipeline, noise-seed, and
multi-chip settings are applied to its managed `SidChip` instances. Use
`c64sid.sid.playback.PlaybackCoordinator` when CPU, CIA, VIC, and memory-map
behavior are required.

Run the deterministic smoke checks from the repository root:

```bash
python3 patches/verify_installation.py
```

Individual helper modules may evolve independently; test them before using them
for research or production work.
