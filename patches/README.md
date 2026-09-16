# Enhanced SID Emulator Patches
## Experimental C64 SID Enhancement Components

**Version:** 1.0.0
**Generated:** 2026-01-11
**License:** Same as parent project

This patch collection provides experimental timing, filter, waveform, ADSR, and deterministic-DSP components. It is not a substitute for hardware validation or a claim of complete cycle accuracy.

## What's Included

✅ **VIC-II DMA** - Full badline + sprite cycle stealing
✅ **CIA Timers** - One-shot mode, cascading, CNT edge counting
✅ **SID Filter** - Non-linear 6581 resonance, accurate cutoff mapping
✅ **Waveforms** - Combined waveform tables with hardware artifacts
✅ **ADSR** - Attack→Decay bug, zero-attack bypass
✅ **Deterministic DSP** - Cross-platform floating-point consistency
✅ **Noise LFSR** - Configurable seeds (6581/8580/custom)
✅ **Bus Persistence** - Color RAM, temperature-dependent decay
✅ **Voice 3 Control** - Output disable nuances
✅ **Test Vectors** - Cycle-exact validation suite

## Quick Start

```python
from patches.integration import create_enhanced_emulator

# Create emulator with maximum accuracy
emulator = create_enhanced_emulator(
    model='6581',
    enable_all_bugs=True,
    enable_dma=True,
    deterministic=True
)

# Reset and use
emulator.reset()
emulator.step(1000)  # Advance 1000 cycles
```

See full documentation in README.md for detailed usage, configuration, and API reference.

## Files

- `vic_dma_enhanced.py` - VIC-II DMA cycle stealing
- `cia_timer_enhanced.py` - CIA timer edge cases
- `sid_filter_enhanced.py` - Non-linear filter
- `combined_waveforms.py` - Waveform tables
- `adsr_enhanced.py` - ADSR with bugs
- `deterministic_components.py` - DSP, noise, bus persistence
- `cycle_exact_tests.py` - Test vectors
- `integration.py` - Integration layer
- `README.md` - Full documentation

## Performance Impact

Total overhead with all features: ~25%

Individual features can be disabled for better performance.
