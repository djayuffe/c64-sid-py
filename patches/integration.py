"""Small configuration wrapper around the maintained SID renderer.

The individual modules in :mod:`patches` are experimental components intended
for direct evaluation. This wrapper exposes only options applied to audio.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from c64sid.logger import SystemLogger
from c64sid.sid.sid_chip import SidChip
from c64sid.sid.sid_types import C64Config


class EnhancedEmulatorConfig:
    """Options applied to each managed :class:`~c64sid.sid.sid_chip.SidChip`."""

    def __init__(self) -> None:
        self.model: Literal['6581', '8580'] = '6581'
        self.clock_hz: int = 985_248
        self.num_chips: int = 1
        self.enable_combined_waveforms: bool = True
        self.enable_adsr_pipeline: bool = True
        self.noise_lfsr_seed: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'model': self.model,
            'clock_hz': self.clock_hz,
            'num_chips': self.num_chips,
            'features': {
                'combined_waveforms': self.enable_combined_waveforms,
                'adsr_pipeline': self.enable_adsr_pipeline,
            },
            'noise': {'lfsr_seed': self.noise_lfsr_seed},
        }


class EnhancedEmulator:
    """Manage one or more deterministic SID register models.

    For full C64 execution, including CPU, CIA, and VIC interactions, use
    :class:`c64sid.sid.c64_system.C64System` through ``PlaybackCoordinator``.
    """

    def __init__(self, config: EnhancedEmulatorConfig):
        if config.model not in ('6581', '8580'):
            raise ValueError(f'Unsupported SID model: {config.model}')
        if not 1 <= int(config.num_chips) <= 3:
            raise ValueError('num_chips must be in the range 1..3')
        if int(config.clock_hz) <= 0:
            raise ValueError('clock_hz must be positive')

        self.config = config
        self.current_cycle = 0
        self.sids = [self._create_sid() for _ in range(config.num_chips)]
        SystemLogger.log(
            'Enhanced-Emulator',
            f'Initialized {config.num_chips} SID chip(s), model={config.model}',
            'info',
            category='init',
        )

    def _create_sid(self) -> SidChip:
        sid_config = C64Config(
            enableAdsrPipeline=bool(self.config.enable_adsr_pipeline),
            enableCombinedWaveforms=bool(self.config.enable_combined_waveforms),
            noiseSeed=(
                0x7FFFFF if self.config.noise_lfsr_seed is None
                else int(self.config.noise_lfsr_seed)
            ),
        )
        sid = SidChip(int(self.config.clock_hz), sid_config)
        sid.set_model(self.config.model)
        return sid

    def reset(self) -> None:
        self.current_cycle = 0
        for sid in self.sids:
            sid.reset()

    def step(self, cycles: int = 1) -> None:
        count = max(0, int(cycles))
        for sid in self.sids:
            sid.update(count)
        self.current_cycle += count

    def get_cycle(self) -> int:
        return self.current_cycle

    def write_register(self, register: int, value: int, *, chip: int = 0) -> None:
        if not 0 <= int(chip) < len(self.sids):
            raise ValueError(f'SID chip index out of range: {chip}')
        if not 0 <= int(register) <= 0x1C:
            raise ValueError(f'SID register out of range: {register}')
        self.sids[int(chip)].write(int(register), int(value) & 0xFF)

    def get_sample(self) -> int:
        sample = sum(sid.render_sample() for sid in self.sids) / len(self.sids)
        return max(-32768, min(32767, int(round(sample * 32767.0))))

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            'cycle': self.current_cycle,
            'config': self.config.to_dict(),
            'chips': [sid.snapshot_forensic() for sid in self.sids],
        }


def create_enhanced_emulator(
    model: Literal['6581', '8580'] = '6581',
    *,
    combined_waveforms: bool = True,
    adsr_pipeline: bool = True,
    noise_seed: Optional[int] = None,
    num_chips: int = 1,
) -> EnhancedEmulator:
    """Create a SID-only experimental emulator with applied audio options."""
    config = EnhancedEmulatorConfig()
    config.model = model
    config.num_chips = num_chips
    config.enable_combined_waveforms = combined_waveforms
    config.enable_adsr_pipeline = adsr_pipeline
    config.noise_lfsr_seed = noise_seed
    return EnhancedEmulator(config)


def create_test_emulator() -> EnhancedEmulator:
    """Create the deterministic configuration used by component smoke tests."""
    return create_enhanced_emulator(noise_seed=0x7FFFF8)
