# Enhanced SID Patches - Quick Reference Guide

## Installation (30 seconds)

```bash
# Extract patches
unzip c64sid_0.1.0.zip
cd enhanced_sid_patches

# Install into your emulator
python install_patches.py /path/to/your/emulator

# Verify
python verify_installation.py
```

## Basic Usage (1 minute)

```python
from patches.integration import create_enhanced_emulator

# Create emulator with ALL features
emu = create_enhanced_emulator(
    model='6581',           # or '8580'
    enable_all_bugs=True,   # Maximum accuracy
    enable_dma=True,        # VIC-II cycle stealing
    deterministic=True      # Cross-platform identical
)

# Use it
emu.reset()
emu.step(1000)  # Run 1000 cycles
```

## Feature Flags

```python
# Individual control
config = EnhancedEmulatorConfig()
config.enable_vic_dma = True              # VIC-II DMA
config.enable_cia_timer_bugs = True       # CIA edge cases
config.enable_sid_filter_nonlin = True    # Filter resonance
config.enable_combined_waveforms = True   # Waveform tables
config.enable_adsr_bugs = True            # A→D bug
config.enable_deterministic_dsp = True    # Fixed-point
config.enable_bus_persistence = True      # Color RAM

# Hardware bugs
config.enable_adsr_ad_bug = True          # 1-cycle drop
config.enable_adsr_zero_attack = True     # Instant attack

# Calibration
config.noise_lfsr_seed = 0x7FFFF8        # Default seed
config.bus_persist_cycles = 7424          # @ 25°C
config.temperature_celsius = 25.0         # Temperature
config.filter_cutoff_offset_hz = 0.0      # Per-chip
config.filter_resonance_scale = 1.0       # Per-chip
```

## What Each Feature Does

| Feature | Impact | When Needed |
|---------|--------|-------------|
| VIC DMA | CPU timing changes | Demos, raster effects |
| CIA Timers | Interrupt timing | Music players |
| Filter Non-Linear | Sound quality | Filter sweeps |
| Combined Waves | Timbre accuracy | Complex sounds |
| ADSR Bugs | Envelope shape | Percussive sounds |
| Deterministic | Bit-identical | Cross-platform |
| Noise LFSR | Noise sequence | Noise effects |
| Bus Persistence | Color RAM reads | Rare |

## Performance

- **Full accuracy**: ~25% overhead
- **Typical use**: ~10-15% overhead
- **Disable unused features** to improve performance

## Common Configurations

### Maximum Accuracy (Music Production)
```python
emu = create_enhanced_emulator(
    model='6581',
    enable_all_bugs=True,
    deterministic=True
)
```

### Fast Emulation (Playback)
```python
config = EnhancedEmulatorConfig()
config.enable_vic_dma = False
config.enable_deterministic_dsp = False
config.model = '8580'  # Simpler than 6581
emu = EnhancedEmulator(config)
```

### Testing/Validation
```python
emu = create_test_emulator()  # All features, deterministic
```

## Files Overview

| File | Purpose |
|------|---------|
| `integration.py` | Main interface |
| `vic_dma_enhanced.py` | VIC-II DMA |
| `cia_timer_enhanced.py` | CIA timers |
| `sid_filter_enhanced.py` | SID filter |
| `combined_waveforms.py` | Waveform tables |
| `adsr_enhanced.py` | ADSR envelope |
| `deterministic_components.py` | DSP, noise, bus |
| `cycle_exact_tests.py` | Test vectors |
| `install_patches.py` | Installer |
| `README.md` | Full documentation |
| `IMPLEMENTATION_DETAILS.md` | Technical specs |

## Quick Troubleshooting

**Q: Sound is different**
A: Check model (6581 vs 8580), filter calibration, temperature

**Q: Tests failing**
A: Enable deterministic mode, check clock frequency

**Q: Too slow**
A: Disable VIC DMA, use 8580, disable deterministic DSP

**Q: Installation error**
A: Check Python version (3.7+), install dependencies

## Help & Support

1. Read `README.md` for full documentation
2. See `IMPLEMENTATION_DETAILS.md` for technical details
3. Run test suite: `python verify_installation.py`
4. Check configuration: `print(emu.config.to_dict())`

## Version History

- **v0.1.0** (2026-09-16): Experimental component bundle with regression checks

---

**Quick Start Summary:**
1. `unzip` → `install_patches.py` → `verify_installation.py`
2. `from patches.integration import create_enhanced_emulator`
3. `emu = create_enhanced_emulator(model='6581', enable_all_bugs=True)`
4. Done!
