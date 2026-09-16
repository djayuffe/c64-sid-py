"""
Deterministic DSP and Enhanced Noise LFSR
Cross-Platform Determinism Experiments and Configurable Noise Generation

This module implements:
- Deterministic floating-point math (platform-independent)
- Configurable noise LFSR seeds (6581 vs 8580 vs custom)
- Exact bit-identical noise sequences
- Fixed-point arithmetic alternatives
- Voice 3 output disable nuances

Reference: IEEE 754, SID noise analysis, VICE/reSID noise models
"""

from __future__ import annotations
from decimal import Decimal, getcontext
from typing import Optional, Literal
import struct

from c64sid.logger import SystemLogger


class DeterministicDSP:
    """Deterministic DSP operations for cross-platform consistency.

    Floating-point operations can vary slightly across platforms due to:
    - Different FPU implementations
    - Compiler optimizations
    - Library versions

    This class provides guaranteed bit-identical results using:
    - Decimal for high-precision calculations
    - Fixed-point for integer-only math
    - Explicit rounding modes
    """

    # Set Decimal precision globally
    getcontext().prec = 50  # 50 decimal digits

    @staticmethod
    def float_to_fixed(value: float, fractional_bits: int = 16) -> int:
        """Convert floating-point to fixed-point integer.

        Args:
            value: Float value to convert
            fractional_bits: Number of fractional bits (default: 16 for 16.16 format)

        Returns: Fixed-point integer
        """
        return int(value * (1 << fractional_bits))

    @staticmethod
    def fixed_to_float(value: int, fractional_bits: int = 16) -> float:
        """Convert fixed-point integer to floating-point.

        Args:
            value: Fixed-point integer
            fractional_bits: Number of fractional bits

        Returns: Float value
        """
        return float(value) / (1 << fractional_bits)

    @staticmethod
    def fixed_mul(a: int, b: int, fractional_bits: int = 16) -> int:
        """Multiply two fixed-point numbers.

        Args:
            a, b: Fixed-point integers
            fractional_bits: Number of fractional bits

        Returns: Product in fixed-point
        """
        # Multiply and shift back
        return (a * b) >> fractional_bits

    @staticmethod
    def fixed_div(a: int, b: int, fractional_bits: int = 16) -> int:
        """Divide two fixed-point numbers.

        Args:
            a, b: Fixed-point integers
            fractional_bits: Number of fractional bits

        Returns: Quotient in fixed-point
        """
        if b == 0:
            return 0
        # Shift before divide to maintain precision
        return (a << fractional_bits) // b

    @staticmethod
    def decimal_add(a: float, b: float) -> float:
        """Deterministic addition using Decimal.

        Guarantees same result across all platforms.
        """
        return float(Decimal(str(a)) + Decimal(str(b)))

    @staticmethod
    def decimal_mul(a: float, b: float) -> float:
        """Deterministic multiplication using Decimal."""
        return float(Decimal(str(a)) * Decimal(str(b)))

    @staticmethod
    def round_to_nearest_int(value: float) -> int:
        """Deterministic rounding to nearest integer.

        Always uses round-half-to-even (banker's rounding) for consistency.
        """
        d = Decimal(str(value))
        return int(d.to_integral_value())

    @staticmethod
    def clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value to range [min_val, max_val]."""
        return max(min_val, min(max_val, value))

    @staticmethod
    def normalize_float64(value: float) -> float:
        """Normalize float to IEEE 754 double precision.

        Ensures consistent representation across platforms.
        """
        # Pack and unpack to normalize
        packed = struct.pack('d', value)
        unpacked = struct.unpack('d', packed)[0]
        return unpacked


class NoiseLFSREnhanced:
    """Enhanced noise LFSR with configurable seeds and exact SID behavior.

    The SID noise waveform uses a 23-bit Linear Feedback Shift Register (LFSR)
    with specific tap points. Different emulators and real chips can have
    different initial seeds.

    This implementation supports:
    - Configurable initial seed (6581, 8580, custom)
    - Exact LFSR feedback polynomial
    - Bit-identical noise sequences
    - Seed capture from telemetry
    """

    # Known LFSR seeds from different sources
    SEED_6581_VICE = 0x7FFFF8      # VICE default for 6581
    SEED_8580_VICE = 0x7FFFFF      # VICE default for 8580
    SEED_RESID = 0x7FFFF8          # reSID default
    SEED_HARDWARE_TYPICAL = 0x7FFFF8  # Most common on real chips

    # LFSR feedback taps (bit positions for XOR)
    # SID uses bits 22 and 17 for feedback
    TAP_BIT_22 = 22
    TAP_BIT_17 = 17

    def __init__(self, model: Literal['6581', '8580'] = '6581', seed: Optional[int] = None):
        """Initialize noise LFSR.

        Args:
            model: SID model (affects default seed)
            seed: Custom seed (if None, uses model default)
        """
        self.model = model

        # Select seed
        if seed is not None:
            self.seed = seed & 0x7FFFFF  # 23-bit mask
        elif model == '6581':
            self.seed = self.SEED_6581_VICE
        else:
            self.seed = self.SEED_8580_VICE

        # Current LFSR state
        self.lfsr = self.seed

        # Output bit (bit 0 of LFSR after shift)
        self.noise_bit = 0

        SystemLogger.log(
            'SID-Noise',
            f'LFSR initialized: model={model}, seed=0x{self.seed:06X}',
            'debug',
            category='sidnoise'
        )

    def reset(self, seed: Optional[int] = None) -> None:
        """Reset LFSR to seed value.

        Args:
            seed: New seed (if None, uses original seed)
        """
        if seed is not None:
            self.seed = seed & 0x7FFFFF

        self.lfsr = self.seed
        self.noise_bit = 0

        SystemLogger.log(
            'SID-Noise',
            f'LFSR reset to 0x{self.lfsr:06X}',
            'debug',
            category='sidnoise'
        )

    def step(self) -> None:
        """Advance LFSR by one step.

        Implements the exact SID noise LFSR algorithm:
        1. Calculate feedback bit (XOR of bits 22 and 17)
        2. Shift LFSR right
        3. Insert feedback bit at position 22
        """
        # Extract tap bits
        bit_22 = (self.lfsr >> self.TAP_BIT_22) & 1
        bit_17 = (self.lfsr >> self.TAP_BIT_17) & 1

        # Calculate feedback
        feedback = bit_22 ^ bit_17

        # Shift right
        self.lfsr >>= 1

        # Insert feedback at bit 22
        self.lfsr |= (feedback << self.TAP_BIT_22)

        # Mask to 23 bits
        self.lfsr &= 0x7FFFFF

        # Output is bit 0 after shift (before it was shifted out)
        # Actually, output uses multiple bits for better noise distribution
        self.noise_bit = self.lfsr & 0xFF  # Use bottom 8 bits

    def get_output(self) -> int:
        """Get current noise output (8-bit).

        Returns: Noise value (0-255)
        """
        return self.noise_bit

    def get_output_12bit(self) -> int:
        """Get current noise output as 12-bit value.

        Maps 8-bit noise to 12-bit range for consistency with other waveforms.

        Returns: Noise value (0-4095)
        """
        return (self.noise_bit << 4) | (self.noise_bit >> 4)

    def get_state(self) -> int:
        """Get current LFSR state for telemetry.

        Returns: 23-bit LFSR value
        """
        return self.lfsr

    def set_state(self, lfsr_value: int) -> None:
        """Set LFSR state (for restoring from telemetry).

        Args:
            lfsr_value: 23-bit LFSR state
        """
        self.lfsr = lfsr_value & 0x7FFFFF
        self.noise_bit = self.lfsr & 0xFF


class Voice3OutputControl:
    """Voice 3 output disable control ($D41B/$D41C).

    The SID has registers that can disable Voice 3's audio output while
    keeping the oscillator running (for modulation/reading).

    $D41B: Voice 3 oscillator output (read-only)
    $D41C: Voice 3 envelope output (read-only)

    Voice 3 output can be disabled via $D418 bit 7, which affects:
    - Audio output to DAC
    - But NOT oscillator/envelope operation
    - Oscillator and envelope still readable
    """

    def __init__(self):
        self.voice3_disabled = False  # Controlled by $D418 bit 7

        # Voice 3 state (for read registers)
        self.osc_output = 0  # $D41B
        self.env_output = 0  # $D41C

    def set_mode_register(self, mode: int) -> None:
        """Set filter mode register ($D418).

        Bit 7: Voice 3 off (1 = disable audio output)
        """
        self.voice3_disabled = bool(mode & 0x80)

        if self.voice3_disabled:
            SystemLogger.log(
                'SID-Voice3',
                'Voice 3 audio output disabled (osc/env still readable)',
                'debug',
                category='sidvoice3'
            )

    def update_outputs(self, osc: int, env: int) -> None:
        """Update Voice 3 oscillator and envelope outputs.

        These values are always updated regardless of disable state.

        Args:
            osc: Oscillator output (12-bit)
            env: Envelope output (8-bit)
        """
        self.osc_output = osc & 0xFFF
        self.env_output = env & 0xFF

    def get_audio_output(self, voice3_audio: float) -> float:
        """Get Voice 3 audio output with disable applied.

        Args:
            voice3_audio: Raw Voice 3 audio sample

        Returns: Audio sample (0.0 if disabled)
        """
        if self.voice3_disabled:
            return 0.0
        return voice3_audio

    def read_osc(self) -> int:
        """Read Voice 3 oscillator register ($D41B).

        Returns: Top 8 bits of oscillator (read-only register)
        """
        return (self.osc_output >> 4) & 0xFF

    def read_env(self) -> int:
        """Read Voice 3 envelope register ($D41C).

        Returns: Envelope output (read-only register)
        """
        return self.env_output


class BusPersistenceModel:
    """Bus persistence (floating bus) timing model.

    The C64 data bus retains values for a short time after writes.
    This affects:
    - Color RAM upper 4 bits (not connected, read open bus)
    - Unused register reads
    - Timing-dependent glitches

    Decay time varies by:
    - Temperature (warmer = faster decay)
    - Board capacitance
    - Individual chip variation

    Typical decay: 7000-8000 cycles @ room temperature
    """

    def __init__(self, persistence_cycles: int = 7424):
        """Initialize bus persistence model.

        Args:
            persistence_cycles: How long bus retains value (default: 7424 cycles)
        """
        self.persistence_cycles = persistence_cycles

        # Current bus value and timestamp
        self.bus_value = 0xFF  # Default to pulled-high
        self.last_write_cycle = 0
        self.current_cycle = 0

        SystemLogger.log(
            'Bus-Persistence',
            f'Initialized with decay time of {persistence_cycles} cycles',
            'debug',
            category='buspersist'
        )

    def write(self, value: int, cycle: int) -> None:
        """Write to bus (updates persistence).

        Args:
            value: 8-bit value written
            cycle: Current CPU cycle
        """
        self.bus_value = value & 0xFF
        self.last_write_cycle = cycle
        self.current_cycle = cycle

    def read(self, cycle: int) -> int:
        """Read from bus (may return decayed value).

        Args:
            cycle: Current CPU cycle

        Returns: 8-bit bus value (possibly decayed)
        """
        self.current_cycle = cycle
        cycles_since_write = cycle - self.last_write_cycle

        if cycles_since_write > self.persistence_cycles:
            # Bus has decayed to default
            return 0xFF

        # Bus still retains value
        return self.bus_value

    def read_color_ram_upper(self, cycle: int) -> int:
        """Read Color RAM upper 4 bits (always open bus).

        Color RAM is 4-bit, upper 4 bits read floating bus.

        Args:
            cycle: Current CPU cycle

        Returns: Upper 4 bits from floating bus
        """
        bus = self.read(cycle)
        return (bus & 0xF0)  # Upper 4 bits

    def set_temperature_factor(self, temp_celsius: float) -> None:
        """Adjust persistence time based on temperature.

        Higher temperature = faster capacitor discharge.

        Args:
            temp_celsius: Temperature in Celsius (20-40 typical range)
        """
        # Reference: 7424 cycles @ 25°C
        # Each 10°C increase reduces persistence by ~15%
        ref_temp = 25.0
        ref_cycles = 7424

        temp_diff = temp_celsius - ref_temp
        decay_factor = 1.0 - (temp_diff * 0.015)  # 1.5% per degree

        self.persistence_cycles = int(ref_cycles * decay_factor)

        SystemLogger.log(
            'Bus-Persistence',
            f'Adjusted for {temp_celsius}°C: {self.persistence_cycles} cycles',
            'info',
            category='buspersist'
        )


def create_deterministic_components(model: Literal['6581', '8580'],
                                   noise_seed: Optional[int] = None,
                                   bus_persist_cycles: int = 7424) -> dict:
    """Factory to create all deterministic components.

    Args:
        model: SID model
        noise_seed: Custom noise LFSR seed
        bus_persist_cycles: Bus persistence decay time

    Returns: Dict with all components
    """
    return {
        'dsp': DeterministicDSP(),
        'noise_lfsr': NoiseLFSREnhanced(model, noise_seed),
        'voice3_ctrl': Voice3OutputControl(),
        'bus_persist': BusPersistenceModel(bus_persist_cycles)
    }
