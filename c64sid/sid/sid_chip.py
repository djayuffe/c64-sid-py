from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .sid_types import C64Config, SidModel


def _u8(v: int) -> int:
    return v & 0xFF


def _u16(v: int) -> int:
    return v & 0xFFFF


def _u24(v: int) -> int:
    return v & 0xFFFFFF


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class SidChip:
    """Deterministic SID register model + simple digital synthesis.

    - Register-accurate for 0x00..0x1F
    - POTX/POTY read as 0xFF
    - OSC3/ENV3 readback
    - Open-bus style behaviour for write-only regs when bus_val is provided

    This is *not* an analog-perfect 6581/8580 model; it's designed for correctness & determinism.
    """

    # Hardware-accurate ADSR rate tables (cycles per envelope step)
    ATTACK_CYCLES = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]
    DECAY_CYCLES = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]
    RELEASE_CYCLES = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]

    def __init__(self, clock_hz: int, cfg: Optional[C64Config] = None):
        self.regs = bytearray(0x20)
        self.model: SidModel = 'UNKNOWN'
        self.clock_hz = int(clock_hz)
        self.cfg = cfg or C64Config()

        # Voice state
        self.phase = [0, 0, 0]  # 24-bit
        self.prev_phase = [0, 0, 0]  # Previous phase for sync detection
        self.osc_overflow = [False, False, False]
        self.last_gate_edge = ['none', 'none', 'none']
        self.env = [0, 0, 0]    # 0..255
        self.gate = [False, False, False]
        self.env_state = ['R', 'R', 'R']  # 'A'|'D'|'S'|'R'
        self.env_pipeline = [0, 0, 0]  # Envelope pipeline delay
        self.env_timer = [0, 0, 0]  # Envelope cycle accumulator for accurate timing

        # Simple noise LFSR per voice
        seed = int(getattr(self.cfg, 'noiseSeed', 0x7FFFFF)) & 0x7FFFFF
        self.noise = [0x7FFFFF, 0x7FFFFF, seed if seed != 0 else 0x7FFFFF]

        self.osc3 = 0
        self.env3 = 0

        # Filter state
        self.filter_lp = 0.0
        self.filter_bp = 0.0
        self.filter_hp = 0.0

    def set_model(self, m: SidModel) -> None:
        self.model = m

    def reset(self) -> None:
        for i in range(0x20):
            self.regs[i] = 0
        self.phase = [0, 0, 0]
        self.prev_phase = [0, 0, 0]
        self.osc_overflow = [False, False, False]
        self.last_gate_edge = ['none', 'none', 'none']
        self.env = [0, 0, 0]
        self.gate = [False, False, False]
        self.env_state = ['R', 'R', 'R']
        self.env_pipeline = [0, 0, 0]
        self.env_timer = [0, 0, 0]
        self.osc3 = 0
        self.env3 = 0
        self.filter_lp = 0.0
        self.filter_bp = 0.0
        self.filter_hp = 0.0

    def read(self, reg: int, bus_val: Optional[int] = None) -> int:
        r = reg & 0x1F
        if r in (0x19, 0x1A):
            return 0xFF
        if r == 0x1B:
            return self.osc3 & 0xFF
        if r == 0x1C:
            return self.env3 & 0xFF

        # Most SID regs are write-only; real chip returns open bus.
        if bus_val is not None:
            return _u8(bus_val)
        return self.regs[r]

    def write(self, reg: int, val: int) -> None:
        r = reg & 0x1F
        v = _u8(val)

        # Gate handling on CTRL writes
        if r in (0x04, 0x0B, 0x12):
            voice = 0 if r == 0x04 else (1 if r == 0x0B else 2)
            old = self.regs[r]
            old_gate = (old & 0x01) != 0
            new_gate = (v & 0x01) != 0
            if (not old_gate) and new_gate:
                self.gate[voice] = True
                self.env_state[voice] = 'A'
                self.last_gate_edge[voice] = 'rise'
            elif old_gate and (not new_gate):
                self.gate[voice] = False
                self.env_state[voice] = 'R'
                self.last_gate_edge[voice] = 'fall'

        self.regs[r] = v

    def update(self, cpu_cycles: int) -> None:
        cc = max(0, int(cpu_cycles))

        for i in range(3):
            # Save previous phase for sync detection
            self.prev_phase[i] = self.phase[i]

            freq = self._get_voice_freq(i)
            # Phase accumulator increments by freq per cycle (no left shift)
            # Formula: f_out = (freq * clock_hz) / 16777216
            inc = freq
            new_phase = _u24(self.phase[i] + (inc * cc))
            self.osc_overflow[i] = bool(new_phase < self.prev_phase[i])

            # Hard sync: if this voice wrapped and next voice has sync enabled, reset next voice
            if new_phase < self.prev_phase[i]:  # Phase wrapped through 0
                if i < 2:  # Voice 0 or 1 can sync voice 1 or 2
                    next_voice = i + 1
                    next_base = 0x07 if next_voice == 1 else 0x0E
                    next_ctrl = self.regs[next_base + 0x04]
                    if next_ctrl & 0x02:  # Sync bit set on next voice
                        self.phase[next_voice] = 0

            self.phase[i] = new_phase

            # advance noise a little with phase
            self._step_noise(i, freq, cc)
            self._step_envelope(i, cc)

            # Commit pipeline to actual envelope
            if self.cfg.enableAdsrPipeline:
                self.env[i] = self.env_pipeline[i]

        self.osc3 = (self.phase[2] >> 16) & 0xFF
        self.env3 = self.env[2] & 0xFF

    # --- Audio ---
    def render_sample(self) -> float:
        """Return one audio sample in range [-1,1] using current SID state.

        Caller controls sampling cadence by calling update() with matching CPU cycles between samples.
        """
        voice_out = [0.0, 0.0, 0.0]

        for v in range(3):
            base = 0x00 if v == 0 else (0x07 if v == 1 else 0x0E)
            ctrl = self.regs[base + 0x04]
            amp = self.env[v] / 255.0

            if ctrl & 0x08:  # TEST: output is forced to 0 on many chips
                continue

            wave = 0.0
            ph = self.phase[v]

            # Oscillator sync: phase was already reset in update() if sync occurred
            # No additional logic needed here - just use current phase

            # Ring modulation: XOR top bit with previous voice
            ring_mod = False
            if (ctrl & 0x04) and v > 0:  # RING bit
                ring_source = (v - 1) % 3
                ring_mod = True

            # Waveform selection and generation
            wave = 0.0
            waveform_bits = (ctrl >> 4) & 0x0F

            if waveform_bits == 0:
                # No waveform selected - output 0
                wave = 0.0
            elif bin(waveform_bits).count('1') == 1:
                # Single waveform - optimized path
                # Triangle
                if ctrl & 0x10:
                    t = (ph >> 12) & 0xFFF
                    # Apply ring modulation
                    if ring_mod:
                        ring_source = (v - 1) % 3
                        if self.phase[ring_source] & 0x800000:
                            t = 0xFFF - t
                    else:
                        if ph & 0x800000:
                            t = 0xFFF - t
                    wave = (t / 2047.5) - 1.0

                # Saw
                elif ctrl & 0x20:
                    s = (ph >> 8) & 0xFFFF
                    wave = (s / 32767.5) - 1.0

                # Pulse
                elif ctrl & 0x40:
                    pw = self._get_voice_pw(v)
                    # compare top 12 bits of phase against pw
                    top = (ph >> 12) & 0xFFF
                    wave = 1.0 if top < pw else -1.0

                # Noise
                elif ctrl & 0x80:
                    n = self.noise[v] & 0x7FFFFF
                    # map 23-bit to [-1,1]
                    wave = ((n / 0x3FFFFF) - 1.0)
            else:
                # Multiple waveforms selected
                # Real hardware combines via digital logic gates (complex)
                # This is an improved approximation using weighted average
                wave_sum = 0.0
                wave_count = 0

                # Triangle
                if ctrl & 0x10:
                    t = (ph >> 12) & 0xFFF
                    if ring_mod:
                        ring_source = (v - 1) % 3
                        if self.phase[ring_source] & 0x800000:
                            t = 0xFFF - t
                    else:
                        if ph & 0x800000:
                            t = 0xFFF - t
                    wave_sum += (t / 2047.5) - 1.0
                    wave_count += 1

                # Saw
                if ctrl & 0x20:
                    s = (ph >> 8) & 0xFFFF
                    wave_sum += (s / 32767.5) - 1.0
                    wave_count += 1

                # Pulse
                if ctrl & 0x40:
                    pw = self._get_voice_pw(v)
                    top = (ph >> 12) & 0xFFF
                    wave_sum += 1.0 if top < pw else -1.0
                    wave_count += 1

                # Noise
                if ctrl & 0x80:
                    n = self.noise[v] & 0x7FFFFF
                    wave_sum += ((n / 0x3FFFFF) - 1.0)
                    wave_count += 1

                # Normalize by count (improved vs simple addition)
                if wave_count > 0:
                    wave = wave_sum / wave_count

            voice_out[v] = wave * amp

        # Voice 3 off bit (bit 7 of $D418)
        vol_control = self.regs[0x18]
        if vol_control & 0x80:
            voice_out[2] = 0.0

        # Filter routing (bit pattern in $D417 and $D418)
        filt_mode = self.regs[0x18]
        filt_route = self.regs[0x17]

        # Which voices go through filter
        v1_filt = (filt_route & 0x01) != 0
        v2_filt = (filt_route & 0x02) != 0
        v3_filt = (filt_route & 0x04) != 0

        # Separate filtered and direct paths
        filt_in = 0.0
        direct_out = 0.0

        if v1_filt:
            filt_in += voice_out[0]
        else:
            direct_out += voice_out[0]

        if v2_filt:
            filt_in += voice_out[1]
        else:
            direct_out += voice_out[1]

        if v3_filt:
            filt_in += voice_out[2]
        else:
            direct_out += voice_out[2]

        # Apply filter if any voice is routed through it
        filt_out = 0.0
        if filt_in != 0.0:
            # Get filter parameters
            cutoff_lo = self.regs[0x15]
            cutoff_hi = self.regs[0x16]
            cutoff = (cutoff_hi << 3) | (cutoff_lo & 0x07)

            # Map cutoff to frequency (exponential approximation for 6581/8580)
            # Real SID has non-linear curve, this is better approximation
            # 6581: roughly exponential, 8580: more linear but still curved
            if cutoff == 0:
                fc = 0.0
            else:
                # Exponential mapping: fc = k * 2^(cutoff/N)
                # Normalized to roughly match hardware response
                import math
                fc = 0.02 * math.pow(2.0, cutoff / 256.0)
                fc = min(fc, 0.45)  # Cap at Nyquist-safe value

            res = (self.regs[0x17] >> 4) & 0x0F
            q = 1.0 / (1.0 + res * 0.06)  # Resonance as damping factor

            # State variable filter (simplified)
            self.filter_bp = self.filter_bp - fc * self.filter_bp * q
            self.filter_lp = self.filter_lp + fc * self.filter_bp
            self.filter_bp = self.filter_bp + fc * (filt_in - self.filter_lp)
            self.filter_hp = filt_in - self.filter_lp - q * self.filter_bp

            # Select filter mode
            lp_en = (filt_mode & 0x10) != 0
            bp_en = (filt_mode & 0x20) != 0
            hp_en = (filt_mode & 0x40) != 0

            if lp_en:
                filt_out += self.filter_lp
            if bp_en:
                filt_out += self.filter_bp
            if hp_en:
                filt_out += self.filter_hp

        mix = direct_out + filt_out

        # Master volume (lower 4 bits of $D418)
        vol = vol_control & 0x0F
        mix *= (vol / 15.0)

        # Soft clip
        return _clamp(mix / 3.0, -1.0, 1.0)

    # --- Forensic / SID-PRO ---

    def snapshot_forensic(self, *, verbose: bool = True) -> dict:
        """Return a compact snapshot suitable for SID-PRO telemetry.

        If verbose=False, this keeps the payload small (frame telemetry).
        If verbose=True, it adds silicon-facing observables (phase/lfsr bits, counters).
        """

        def env_rate(v: int) -> int:
            base = 0x00 if v == 0 else (0x07 if v == 1 else 0x0E)
            ad = self.regs[base + 0x05]
            sr = self.regs[base + 0x06]
            atk = (ad >> 4) & 0x0F
            dec = ad & 0x0F
            rel = sr & 0x0F
            st = self.env_state[v]
            if st == 'A':
                return int(self.ATTACK_CYCLES[atk])
            if st in ('D', 'S'):
                return int(self.DECAY_CYCLES[dec])
            return int(self.RELEASE_CYCLES[rel])

        voices = []
        for v in range(3):
            base = 0x00 if v == 0 else (0x07 if v == 1 else 0x0E)
            freq = (self.regs[base + 0x01] << 8) | self.regs[base + 0x00]
            pw = ((self.regs[base + 0x03] & 0x0F) << 8) | self.regs[base + 0x02]
            ctrl = self.regs[base + 0x04]
            ad = self.regs[base + 0x05]
            sr = self.regs[base + 0x06]
            wave = (ctrl >> 4) & 0x0F

            phase24 = int(self.phase[v] & 0xFFFFFF)
            phase4 = int((self.phase[v] >> 20) & 0x0F)
            lfsr23 = int(self.noise[v] & 0x7FFFFF)

            # Pulse comparator uses top 12 bits vs PW
            phase12 = int((self.phase[v] >> 12) & 0x0FFF)
            pulse_out = 1 if phase12 < int(pw) else 0
            noise_out_bit = int((self.noise[v] >> 22) & 1)
            noise_out_byte = int((self.noise[v] >> 15) & 0xFF)

            osc = {
                "acc": phase24,
                "phase4": phase4,
                "phase4_hex": f"{phase4:X}",
                "lfsr": lfsr23,
                "lfsr_hex": f"{lfsr23:06X}",
            }
            if verbose:
                osc.update(
                    {
                        "overflow": bool(self.osc_overflow[v]),
                        "pulse_phase12": phase12,
                        "pulse_out": int(pulse_out),
                        "noise_out_bit": int(noise_out_bit),
                        "noise_out_byte": int(noise_out_byte),
                    }
                )

            env = {
                "out": int(self.env[v] & 0xFF),
                "out_hex": f"{(self.env[v] & 0xFF):02X}",
                "state": str(self.env_state[v]),
                "counter": int(self.env_pipeline[v] & 0xFF),
                "counter_hex": f"{(self.env_pipeline[v] & 0xFF):02X}",
                "rate": int(env_rate(v)),
            }
            if verbose:
                atk = (ad >> 4) & 0x0F
                dec = ad & 0x0F
                sus = (sr >> 4) & 0x0F
                rel = sr & 0x0F
                env.update(
                    {
                        "rate_counter": int(self.env_timer[v] & 0xFFFFFFFF),
                        "atk_rate": int(self.ATTACK_CYCLES[atk]),
                        "dec_rate": int(self.DECAY_CYCLES[dec]),
                        "rel_rate": int(self.RELEASE_CYCLES[rel]),
                        "sus_level": int(sus * 17),
                    }
                )

            derived = {
                "wave": int(wave),
                "test": bool(ctrl & 0x08),
                "ring": bool(ctrl & 0x04),
                "sync": bool(ctrl & 0x02),
                "gate": bool(ctrl & 0x01),
                "freq_hz": float(freq) * float(self.clock_hz) / 16777216.0,
            }
            if verbose:
                derived.update(
                    {
                        "gate_edge": str(self.last_gate_edge[v]),
                        "osc_overflow": bool(self.osc_overflow[v]),
                        "pulse_out": int(pulse_out),
                        "noise_out_bit": int(noise_out_bit),
                        "test_active": bool(ctrl & 0x08),
                    }
                )

            voices.append(
                {
                    "osc": osc,
                    "env": env,
                    "reg": {"freq": int(freq), "pw": int(pw), "ctrl": int(ctrl), "ad": int(ad), "sr": int(sr)},
                    "derived": derived,
                }
            )

        # Clear latched edge markers once observed
        if verbose:
            for i in range(3):
                self.last_gate_edge[i] = 'none'

        cutoff_lo = self.regs[0x15]
        cutoff_hi = self.regs[0x16]
        cutoff = (cutoff_hi << 3) | (cutoff_lo & 0x07)
        res_route = self.regs[0x17]
        vol_mode = self.regs[0x18]
        resonance = (res_route >> 4) & 0x0F
        filter_mode = (vol_mode >> 4) & 0x07

        filter_state = {
            "cutoff": int(cutoff & 0x7FF),
            "res": int(resonance),
            "mode": int(filter_mode),
            "voice_mask": int(res_route & 0x0F),
            "hp_int": float(self.filter_hp),
            "bp_int": float(self.filter_bp),
            "lp_int": float(self.filter_lp),
            "vol": int(vol_mode & 0x0F),
            "voice3_off": bool(vol_mode & 0x80),
        }

        return {
            "registers": [int(x) for x in self.regs],
            "voices": voices,
            "filter": filter_state,
        }

    def _get_voice_freq(self, v: int) -> int:
        base = 0x00 if v == 0 else (0x07 if v == 1 else 0x0E)
        lo = self.regs[base + 0x00]
        hi = self.regs[base + 0x01]
        return (hi << 8) | lo

    def _get_voice_pw(self, v: int) -> int:
        base = 0x00 if v == 0 else (0x07 if v == 1 else 0x0E)
        lo = self.regs[base + 0x02]
        hi = self.regs[base + 0x03] & 0x0F
        return (hi << 8) | lo

    def _step_noise(self, v: int, freq: int, cycles: int) -> None:
        # Noise LFSR clocked at bit 19 of phase accumulator
        # Shifts occur at approximately freq/(2^19) rate
        if freq == 0:
            return

        # Calculate approximate number of shifts based on frequency and cycles
        # More accurate than fixed rate, accounts for voice frequency
        total_phase_inc = freq * cycles
        shifts = total_phase_inc >> 19  # Number of bit 19 transitions

        if shifts > 0:
            x = self.noise[v] & 0x7FFFFF
            # Cap shifts to prevent performance issues
            for _ in range(min(int(shifts), 128)):
                # 23-bit LFSR with taps at bits 22 and 17
                b = ((x >> 22) ^ (x >> 17)) & 1
                x = ((x << 1) & 0x7FFFFF) | b
            self.noise[v] = x

    def _step_envelope(self, v: int, cycles: int) -> None:
        base = 0x00 if v == 0 else (0x07 if v == 1 else 0x0E)
        ad = self.regs[base + 0x05]
        sr = self.regs[base + 0x06]
        atk = (ad >> 4) & 0x0F
        dec = ad & 0x0F
        sus = (sr >> 4) & 0x0F
        rel = sr & 0x0F

        # Use hardware-accurate rate tables
        atk_rate = self.ATTACK_CYCLES[atk]
        dec_rate = self.DECAY_CYCLES[dec]
        rel_rate = self.RELEASE_CYCLES[rel]
        sus_level = sus * 17

        # Accumulate cycles for envelope timing
        self.env_timer[v] += max(0, int(cycles))

        # Apply pipeline delay if enabled
        if self.cfg.enableAdsrPipeline:
            target_env = self.env_pipeline[v]
        else:
            target_env = int(self.env[v])

        e = target_env
        st = self.env_state[v]

        if st == 'A':
            # Attack: increment by 1 every atk_rate cycles
            steps = self.env_timer[v] // atk_rate
            self.env_timer[v] %= atk_rate
            e = min(255, e + steps)
            if e >= 255:
                self.env_state[v] = 'D'
                e = 255

        elif st == 'D':
            # Decay: decrement by 1 every dec_rate cycles
            steps = self.env_timer[v] // dec_rate
            self.env_timer[v] %= dec_rate
            e = max(sus_level, e - steps)
            if e <= sus_level:
                self.env_state[v] = 'S'
                e = sus_level

        elif st == 'S':
            # Sustain: hold at sustain level
            e = sus_level
            self.env_timer[v] = 0  # Reset timer during sustain
            if not self.gate[v]:
                self.env_state[v] = 'R'

        else:  # Release
            # Release: decrement by 1 every rel_rate cycles
            steps = self.env_timer[v] // rel_rate
            self.env_timer[v] %= rel_rate
            e = max(0, e - steps)

        # Pipeline: current output is previous target, new target stored
        if self.cfg.enableAdsrPipeline:
            self.env_pipeline[v] = e & 0xFF
            # Actual envelope lags by 1 cycle (simplified)
        else:
            self.env[v] = e & 0xFF
            self.env_pipeline[v] = e & 0xFF