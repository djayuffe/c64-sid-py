"""
Enhanced SID ADSR Envelope Generator
Experimental ADSR with Attack→Decay Bug Modeling

This module implements:
- Attack→Decay transition bug (1-cycle glitch)
- Exponential decay curves (hardware-accurate)
- Rate counter implementation
- Zero-attack bypass
- Proper state machine transitions

Reference: SID datasheet, VICE ADSR analysis, hermit's research
"""

from __future__ import annotations

from c64sid.logger import SystemLogger


class AdsrEnhanced:
    """Enhanced ADSR envelope generator with hardware bugs.

    The SID ADSR has several documented quirks:
    1. Attack→Decay bug: When transitioning from Attack to Decay, there's
       a 1-cycle glitch where the envelope can drop slightly
    2. Exponential decay uses 9-stage counter, not true exponential
    3. Zero attack bypasses normal rate counter
    4. Rate table has specific clock dividers
    """

    # ADSR states
    STATE_ATTACK = 0
    STATE_DECAY = 1
    STATE_SUSTAIN = 2
    STATE_RELEASE = 3

    # Rate counter periods (in CPU cycles @ 1 MHz)
    # Index by rate value (0-15)
    RATE_PERIODS = [
        9,      # 0: ~9 cycles (shortest)
        32,     # 1
        63,     # 2
        95,     # 3
        149,    # 4
        220,    # 5
        267,    # 6
        313,    # 7
        392,    # 8
        977,    # 9
        1954,   # 10
        3126,   # 11
        3907,   # 12
        11720,  # 13
        19532,  # 14
        31251,  # 15: ~31 ms (longest)
    ]

    # Exponential decay lookup (9 stages)
    # Each stage doubles the period before decrement
    EXP_PERIODS = [1, 30, 30, 30, 30, 30, 16, 16, 16, 16, 16, 16, 8, 8, 8, 8, 8, 8, 8, 8, 4, 4, 4, 4, 2, 2, 2, 2, 1, 1, 1, 1]

    def __init__(self, enable_ad_bug: bool = True, enable_zero_attack_bypass: bool = True):
        """Initialize ADSR envelope.

        Args:
            enable_ad_bug: Enable Attack→Decay transition bug (default: True for accuracy)
            enable_zero_attack_bypass: Enable zero-attack bypass quirk
        """
        self.enable_ad_bug = enable_ad_bug
        self.enable_zero_attack_bypass = enable_zero_attack_bypass

        # Current state
        self.state = self.STATE_RELEASE
        self.output = 0  # 8-bit envelope level (0-255)

        # ADSR parameters
        self.attack_rate = 0    # 4-bit (0-15)
        self.decay_rate = 0     # 4-bit (0-15)
        self.sustain_level = 0  # 4-bit (0-15), scaled to 8-bit
        self.release_rate = 0   # 4-bit (0-15)

        # Rate counter
        self.rate_counter = 0
        self.rate_period = self.RATE_PERIODS[0]

        # Exponential counter (for decay/release)
        self.exp_counter = 0
        self.exp_period = 1

        # Gate state
        self.gate = False

        # Bug tracking
        self._just_entered_decay = False
        self._ad_bug_triggered = False

        SystemLogger.log(
            'SID-ADSR',
            f'ADSR initialized: AD_bug={enable_ad_bug}, zero_attack_bypass={enable_zero_attack_bypass}',
            'debug',
            category='sidadsr'
        )

    def set_attack_decay(self, ad: int) -> None:
        """Set Attack and Decay rates.

        Bits 7-4: Attack rate
        Bits 3-0: Decay rate
        """
        self.attack_rate = (ad >> 4) & 0x0F
        self.decay_rate = ad & 0x0F

        # Update rate period if in attack or decay
        if self.state == self.STATE_ATTACK:
            self.rate_period = self.RATE_PERIODS[self.attack_rate]
        elif self.state == self.STATE_DECAY:
            self.rate_period = self.RATE_PERIODS[self.decay_rate]

    def set_sustain_release(self, sr: int) -> None:
        """Set Sustain level and Release rate.

        Bits 7-4: Sustain level (0-15, scaled to 0-255)
        Bits 3-0: Release rate
        """
        sustain_4bit = (sr >> 4) & 0x0F
        self.sustain_level = sustain_4bit * 17  # Scale to 8-bit (0, 17, 34, ..., 255)
        self.release_rate = sr & 0x0F

        # Update rate period if in release
        if self.state == self.STATE_RELEASE:
            self.rate_period = self.RATE_PERIODS[self.release_rate]

    def set_gate(self, gate: bool) -> None:
        """Set gate bit (starts/stops envelope).

        Gate 1→0: Enter Release
        Gate 0→1: Enter Attack
        """
        old_gate = self.gate
        self.gate = gate

        if gate and not old_gate:
            # Gate rising edge: enter Attack
            self._enter_attack()
        elif not gate and old_gate:
            # Gate falling edge: enter Release
            self._enter_release()

    def _enter_attack(self) -> None:
        """Transition to Attack state."""
        self.state = self.STATE_ATTACK
        self.rate_period = self.RATE_PERIODS[self.attack_rate]
        self.rate_counter = 0

        # Zero attack bypass
        if self.enable_zero_attack_bypass and self.attack_rate == 0:
            # Instant attack to max
            self.output = 255
            self._enter_decay()  # Immediately enter decay
            SystemLogger.log(
                'SID-ADSR',
                'Zero-attack bypass: instant max output',
                'debug',
                category='sidadsr'
            )
        else:
            SystemLogger.log(
                'SID-ADSR',
                f'Enter Attack: rate={self.attack_rate}, period={self.rate_period}',
                'debug',
                category='sidadsr'
            )

    def _enter_decay(self) -> None:
        """Transition to Decay state."""
        self.state = self.STATE_DECAY
        self.rate_period = self.RATE_PERIODS[self.decay_rate]
        self.rate_counter = 0
        self.exp_counter = 0
        self._update_exp_period()

        # Mark that we just entered decay (for A→D bug)
        self._just_entered_decay = True

        SystemLogger.log(
            'SID-ADSR',
            f'Enter Decay: rate={self.decay_rate}, sustain={self.sustain_level}, period={self.rate_period}',
            'debug',
            category='sidadsr'
        )

    def _enter_sustain(self) -> None:
        """Transition to Sustain state."""
        self.state = self.STATE_SUSTAIN
        # Sustain holds at sustain_level, no rate counter

        SystemLogger.log(
            'SID-ADSR',
            f'Enter Sustain: level={self.output}',
            'debug',
            category='sidadsr'
        )

    def _enter_release(self) -> None:
        """Transition to Release state."""
        self.state = self.STATE_RELEASE
        self.rate_period = self.RATE_PERIODS[self.release_rate]
        self.rate_counter = 0
        self.exp_counter = 0
        self._update_exp_period()

        SystemLogger.log(
            'SID-ADSR',
            f'Enter Release: rate={self.release_rate}, from_level={self.output}',
            'debug',
            category='sidadsr'
        )

    def _update_exp_period(self) -> None:
        """Update exponential period based on current output level.

        The SID uses a lookup table that gives longer periods at lower levels
        (creating exponential decay curve).
        """
        # Map 8-bit output to exponential table index (0-31)
        idx = min(31, self.output >> 3)
        self.exp_period = self.EXP_PERIODS[idx]

    def step(self, cycles: int = 1) -> None:
        """Advance ADSR by specified cycles.

        Updates envelope output based on current state and rate counters.
        """
        for _ in range(cycles):
            self._step_one_cycle()

    def _step_one_cycle(self) -> None:
        """Advance ADSR by one cycle."""
        if self.state == self.STATE_ATTACK:
            self._step_attack()
        elif self.state == self.STATE_DECAY:
            self._step_decay()
        elif self.state == self.STATE_SUSTAIN:
            self._step_sustain()
        elif self.state == self.STATE_RELEASE:
            self._step_release()

    def _step_attack(self) -> None:
        """Process one cycle of Attack phase."""
        self.rate_counter += 1

        if self.rate_counter >= self.rate_period:
            self.rate_counter = 0

            # Increment envelope (linear rise in attack)
            if self.output < 255:
                self.output += 1

            # Check if reached max
            if self.output >= 255:
                self.output = 255
                # Transition to Decay
                self._enter_decay()

    def _step_decay(self) -> None:
        """Process one cycle of Decay phase."""
        # Attack→Decay transition bug
        if self._just_entered_decay and self.enable_ad_bug:
            # Bug: on first cycle of decay, envelope can drop 1 level
            if self.output > 0 and not self._ad_bug_triggered:
                self.output -= 1
                self._ad_bug_triggered = True
                SystemLogger.log(
                    'SID-ADSR',
                    f'A→D bug triggered: envelope dropped to {self.output}',
                    'debug',
                    category='sidadsr'
                )
            self._just_entered_decay = False

        self.rate_counter += 1

        if self.rate_counter >= self.rate_period:
            self.rate_counter = 0
            self.exp_counter += 1

            # Exponential decay
            if self.exp_counter >= self.exp_period:
                self.exp_counter = 0

                # Decrement envelope
                if self.output > self.sustain_level:
                    self.output -= 1
                    self._update_exp_period()

                # Check if reached sustain level
                if self.output <= self.sustain_level:
                    self.output = self.sustain_level
                    self._enter_sustain()

    def _step_sustain(self) -> None:
        """Process one cycle of Sustain phase."""
        # Sustain holds at sustain_level
        # Output already set to sustain_level
        pass

    def _step_release(self) -> None:
        """Process one cycle of Release phase."""
        self.rate_counter += 1

        if self.rate_counter >= self.rate_period:
            self.rate_counter = 0
            self.exp_counter += 1

            # Exponential decay (same as decay phase)
            if self.exp_counter >= self.exp_period:
                self.exp_counter = 0

                # Decrement envelope
                if self.output > 0:
                    self.output -= 1
                    self._update_exp_period()

    def get_output(self) -> int:
        """Get current envelope output (8-bit, 0-255).

        Returns: Envelope level
        """
        return self.output

    def get_state_name(self) -> str:
        """Get current state as string."""
        states = ['Attack', 'Decay', 'Sustain', 'Release']
        return states[self.state]

    def get_state_snapshot(self) -> dict:
        """Get complete ADSR state for telemetry.

        Returns: Dict with ADSR state
        """
        return {
            'output': self.output,
            'state': self.state,
            'state_name': self.get_state_name(),
            'attack_rate': self.attack_rate,
            'decay_rate': self.decay_rate,
            'sustain_level': self.sustain_level,
            'release_rate': self.release_rate,
            'rate_counter': self.rate_counter,
            'rate_period': self.rate_period,
            'exp_counter': self.exp_counter,
            'exp_period': self.exp_period,
            'gate': self.gate,
            'ad_bug_enabled': self.enable_ad_bug,
            'ad_bug_triggered': self._ad_bug_triggered
        }


def create_adsr(enable_bugs: bool = True) -> AdsrEnhanced:
    """Factory function to create ADSR envelope generator.

    Args:
        enable_bugs: Enable hardware bugs (AD transition, zero-attack bypass)

    Returns: Configured AdsrEnhanced instance
    """
    return AdsrEnhanced(
        enable_ad_bug=enable_bugs,
        enable_zero_attack_bypass=enable_bugs
    )
