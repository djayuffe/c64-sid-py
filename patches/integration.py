"""
Experimental SID Emulator Integration Layer

The components in this module are useful for experimentation and diagnostics;
they are not a certification of cycle- or hardware-exact emulation.

This module integrates all enhanced components:
- VIC-II DMA (badlines + sprites)
- CIA timers (edge cases + cascading)
- SID filter (non-linear resonance)
- Combined waveforms (hardware tables)
- ADSR (A→D bug)
- Deterministic DSP
- Noise LFSR (configurable seeds)
- Bus persistence
- Voice 3 control

Usage:
    from patches.integration import create_enhanced_emulator

    emulator = create_enhanced_emulator(
        model='6581',
        enable_all_bugs=True,
        enable_dma=True,
        deterministic=True
    )
"""

from __future__ import annotations
from typing import Optional, Literal, Dict, Any

# Import enhanced components
from .vic_dma_enhanced import VicDmaEnhanced
from .cia_timer_enhanced import CiaEnhanced
from .sid_filter_enhanced import create_enhanced_filter
from .combined_waveforms import create_waveform_generator
from .adsr_enhanced import create_adsr
from .deterministic_components import create_deterministic_components
from .cycle_exact_tests import CycleExactTestVectors, TestRunner
from c64sid.logger import SystemLogger
from c64sid.sid.sid_chip import SidChip
from c64sid.sid.sid_types import C64Config


class EnhancedEmulatorConfig:
    """Configuration for enhanced emulator."""

    def __init__(self):
        # SID chip configuration
        self.model: Literal['6581', '8580'] = '6581'
        self.clock_hz: int = 985248  # PAL
        self.num_chips: int = 1

        # Feature flags
        self.enable_vic_dma: bool = True
        self.enable_cia_timer_bugs: bool = True
        self.enable_sid_filter_nonlin: bool = True
        self.enable_combined_waveforms: bool = True
        self.enable_adsr_bugs: bool = True
        self.enable_deterministic_dsp: bool = True
        self.enable_bus_persistence: bool = True

        # Hardware bug flags (can be individually controlled)
        self.enable_adsr_ad_bug: bool = True
        self.enable_adsr_zero_attack: bool = True

        # Noise configuration
        self.noise_lfsr_seed: Optional[int] = None  # None = use default for model

        # Bus persistence
        self.bus_persist_cycles: int = 7424  # Default decay time

        # Temperature (affects filter and bus persistence)
        self.temperature_celsius: float = 25.0

        # Determinism
        self.deterministic_mode: bool = True  # Use fixed-point math

        # Calibration (per-chip variance)
        self.filter_cutoff_offset_hz: float = 0.0
        self.filter_resonance_scale: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as dictionary."""
        return {
            'model': self.model,
            'clock_hz': self.clock_hz,
            'num_chips': self.num_chips,
            'features': {
                'vic_dma': self.enable_vic_dma,
                'cia_timer_bugs': self.enable_cia_timer_bugs,
                'sid_filter_nonlin': self.enable_sid_filter_nonlin,
                'combined_waveforms': self.enable_combined_waveforms,
                'adsr_bugs': self.enable_adsr_bugs,
                'deterministic_dsp': self.enable_deterministic_dsp,
                'bus_persistence': self.enable_bus_persistence,
            },
            'hardware_bugs': {
                'adsr_ad_bug': self.enable_adsr_ad_bug,
                'adsr_zero_attack': self.enable_adsr_zero_attack,
            },
            'noise': {
                'lfsr_seed': self.noise_lfsr_seed,
            },
            'environment': {
                'temperature_celsius': self.temperature_celsius,
                'bus_persist_cycles': self.bus_persist_cycles,
            },
            'calibration': {
                'filter_cutoff_offset_hz': self.filter_cutoff_offset_hz,
                'filter_resonance_scale': self.filter_resonance_scale,
            }
        }


class EnhancedEmulator:
    """Enhanced SID emulator with all patches applied."""

    def __init__(self, config: EnhancedEmulatorConfig):
        """Initialize enhanced emulator.

        Args:
            config: Emulator configuration
        """
        self.config = config

        SystemLogger.log(
            'Enhanced-Emulator',
            f'Initializing enhanced emulator: model={config.model}, '
            f'clock={config.clock_hz} Hz, features={len([k for k,v in config.to_dict()["features"].items() if v])} enabled',
            'info',
            category='init'
        )

        # Create enhanced components
        self._create_components()

        # Integration state
        self.current_cycle = 0.0
        self.sample_buffer = []

        SystemLogger.log(
            'Enhanced-Emulator',
            'Initialization complete',
            'info',
            category='init'
        )

    def _create_components(self) -> None:
        """Create all enhanced components based on configuration."""

        # VIC-II DMA (if enabled)
        if self.config.enable_vic_dma:
            self.vic_dma = VicDmaEnhanced()
            SystemLogger.log(
                'Enhanced-Emulator',
                'VIC-II DMA enabled (badlines + sprites)',
                'info',
                category='init'
            )
        else:
            self.vic_dma = None

        # CIA timers (if enabled)
        if self.config.enable_cia_timer_bugs:
            self.cia1 = CiaEnhanced('CIA1')
            self.cia2 = CiaEnhanced('CIA2')
            SystemLogger.log(
                'Enhanced-Emulator',
                'CIA timer edge cases enabled',
                'info',
                category='init'
            )
        else:
            self.cia1 = None
            self.cia2 = None

        # SID filters (per chip)
        self.filters = []
        if self.config.enable_sid_filter_nonlin:
            for _ in range(self.config.num_chips):
                filt = create_enhanced_filter(self.config.model, self.config.clock_hz)
                filt.cutoff_offset_hz = self.config.filter_cutoff_offset_hz
                filt.resonance_scale = self.config.filter_resonance_scale
                self.filters.append(filt)
            SystemLogger.log(
                'Enhanced-Emulator',
                f'Enhanced filters created ({self.config.model} model)',
                'info',
                category='init'
            )

        # Waveform generators
        self.waveforms = []
        if self.config.enable_combined_waveforms:
            for _ in range(self.config.num_chips):
                wg = create_waveform_generator(self.config.model)
                self.waveforms.append(wg)
            SystemLogger.log(
                'Enhanced-Emulator',
                'Combined waveform tables loaded',
                'info',
                category='init'
            )

        # ADSR envelopes (3 per chip)
        self.adsrs = []
        if self.config.enable_adsr_bugs:
            for chip in range(self.config.num_chips):
                for voice in range(3):
                    adsr = create_adsr(enable_bugs=True)
                    self.adsrs.append(adsr)
            SystemLogger.log(
                'Enhanced-Emulator',
                f'ADSR envelopes created with bugs (AD_bug={self.config.enable_adsr_ad_bug})',
                'info',
                category='init'
            )

        # Deterministic components
        if self.config.enable_deterministic_dsp or self.config.enable_bus_persistence:
            self.det_components = create_deterministic_components(
                model=self.config.model,
                noise_seed=self.config.noise_lfsr_seed,
                bus_persist_cycles=self.config.bus_persist_cycles
            )
            SystemLogger.log(
                'Enhanced-Emulator',
                f'Deterministic components created (noise_seed=0x{self.det_components["noise_lfsr"].seed:06X})',
                'info',
                category='init'
            )

        # The enhanced helpers decorate timing and diagnostics, while the core
        # SID remains the authoritative register and audio implementation.
        self.sids = [SidChip(self.config.clock_hz, C64Config()) for _ in range(self.config.num_chips)]
        for sid in self.sids:
            sid.set_model(self.config.model)

    def reset(self) -> None:
        """Reset all components to power-on state."""
        self.current_cycle = 0.0
        self.sample_buffer = []

        # Reset VIC-II DMA
        if self.vic_dma:
            pass  # VIC DMA is stateless

        # Reset CIA timers
        if self.cia1:
            self.cia1.reset()
        if self.cia2:
            self.cia2.reset()

        # Reset filters
        for filt in self.filters:
            filt.reset()

        # Reset waveforms
        for wg in self.waveforms:
            wg.phase_accumulator = 0

        # Reset ADSR
        for adsr in self.adsrs:
            adsr.output = 0
            adsr.state = adsr.STATE_RELEASE

        # Reset deterministic components
        if hasattr(self, 'det_components'):
            self.det_components['noise_lfsr'].reset()
            self.det_components['bus_persist'].current_cycle = 0

        for sid in self.sids:
            sid.reset()

        SystemLogger.log(
            'Enhanced-Emulator',
            'All components reset to power-on state',
            'debug',
            category='reset'
        )

    def step(self, cycles: int = 1) -> None:
        """Advance emulator by specified cycles.

        Args:
            cycles: Number of CPU cycles to advance
        """
        for _ in range(max(0, int(cycles))):
            self.current_cycle += 1

            # Update CIA timers
            if self.cia1:
                self.cia1.step(1)
            if self.cia2:
                self.cia2.step(1)

            # Update ADSR envelopes
            for adsr in self.adsrs:
                adsr.step(1)

            # Update noise LFSR
            if hasattr(self, 'det_components'):
                self.det_components['noise_lfsr'].step()
            for sid in self.sids:
                sid.update(1)

    def get_cycle(self) -> int:
        """Get current cycle count."""
        return int(self.current_cycle)

    def write_register(self, register: int, value: int) -> None:
        """Write to SID register.

        Args:
            register: Register offset (0x00-0x1C)
            value: 8-bit value
        """
        # Update bus persistence
        if hasattr(self, 'det_components'):
            self.det_components['bus_persist'].write(value, int(self.current_cycle))

        if not 0 <= int(register) <= 0x1C:
            raise ValueError(f'SID register out of range: {register}')
        if not self.sids:
            return
        self.sids[0].write(int(register), int(value) & 0xFF)

    def get_sample(self) -> int:
        """Get current audio sample.

        Returns: 16-bit signed sample
        """
        if not self.sids:
            return 0
        sample = sum(sid.render_sample() for sid in self.sids) / len(self.sids)
        return max(-32768, min(32767, int(round(sample * 32767.0))))

    def get_telemetry(self) -> Dict[str, Any]:
        """Get comprehensive telemetry snapshot.

        Returns: Dict with all component states
        """
        telemetry = {
            'cycle': int(self.current_cycle),
            'config': self.config.to_dict(),
        }

        # Add filter states
        if self.filters:
            telemetry['filters'] = [f.get_state_snapshot() for f in self.filters]

        # Add ADSR states
        if self.adsrs:
            telemetry['adsrs'] = [a.get_state_snapshot() for a in self.adsrs]

        # Add noise LFSR state
        if hasattr(self, 'det_components'):
            telemetry['noise_lfsr'] = {
                'state': self.det_components['noise_lfsr'].get_state(),
                'seed': self.det_components['noise_lfsr'].seed,
            }

        return telemetry


def create_enhanced_emulator(
    model: Literal['6581', '8580'] = '6581',
    enable_all_bugs: bool = True,
    enable_dma: bool = True,
    deterministic: bool = True,
    temperature: float = 25.0,
    noise_seed: Optional[int] = None
) -> EnhancedEmulator:
    """Factory function to create enhanced emulator with common presets.

    Args:
        model: SID model ('6581' or '8580')
        enable_all_bugs: Enable all hardware bugs for accuracy
        enable_dma: Enable VIC-II DMA cycle stealing
        deterministic: Use deterministic DSP for cross-platform consistency
        temperature: Operating temperature in Celsius
        noise_seed: Custom noise LFSR seed (None = default for model)

    Returns: Configured EnhancedEmulator instance
    """
    config = EnhancedEmulatorConfig()
    config.model = model
    config.enable_vic_dma = enable_dma
    config.enable_deterministic_dsp = deterministic
    config.temperature_celsius = temperature
    config.noise_lfsr_seed = noise_seed

    if enable_all_bugs:
        config.enable_cia_timer_bugs = True
        config.enable_sid_filter_nonlin = True
        config.enable_combined_waveforms = True
        config.enable_adsr_bugs = True
        config.enable_bus_persistence = True
        config.enable_adsr_ad_bug = True
        config.enable_adsr_zero_attack = True

    return EnhancedEmulator(config)


def create_test_emulator() -> EnhancedEmulator:
    """Create emulator configured for test vector validation.

    Returns: Emulator with all features enabled and deterministic mode
    """
    return create_enhanced_emulator(
        model='6581',
        enable_all_bugs=True,
        enable_dma=True,
        deterministic=True,
        temperature=25.0,
        noise_seed=0x7FFFF8  # Standard test seed
    )


# Example usage
if __name__ == '__main__':
    # Create enhanced emulator
    emu = create_enhanced_emulator(
        model='6581',
        enable_all_bugs=True
    )

    # Get configuration
    config = emu.config.to_dict()
    print(f"Enhanced emulator created with {len([k for k,v in config['features'].items() if v])} features enabled")

    # Run test vectors
    test_vectors = CycleExactTestVectors()
    runner = TestRunner(emu)
    results = runner.run_all(test_vectors.vectors)

    print(f"Test results: {results['passed']}/{results['total']} passed ({results['pass_rate']*100:.1f}%)")
