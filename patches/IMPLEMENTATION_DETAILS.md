# Enhanced SID Emulator - Complete Implementation Details
## Technical Notes for Experimental Hardware Modeling

**Version:** 1.0.0
**Date:** 2026-01-11

---

## Table of Contents

1. [VIC-II DMA Cycle Stealing](#vic-ii-dma)
2. [CIA Timer Edge Cases](#cia-timers)
3. [SID Filter Non-Linearity](#sid-filter)
4. [Combined Waveforms](#waveforms)
5. [ADSR Bugs](#adsr)
6. [Deterministic DSP](#deterministic)
7. [Noise LFSR](#noise)
8. [Bus Persistence](#bus-persistence)
9. [Voice 3 Control](#voice3)
10. [Test Vectors](#tests)

---

## VIC-II DMA Cycle Stealing {#vic-ii-dma}

### Implementation: vic_dma_enhanced.py

### Hardware Behavior

The VIC-II chip steals CPU bus cycles for:
1. **Badline DMA** - Character matrix fetch (40 cycles)
2. **Sprite Data** - 3 cycles per enabled sprite
3. **Sprite Pointers** - 2 cycles per enabled sprite
4. **Idle Refresh** - 5 cycles at line start

### Badline Timing

```
Badline occurs when:
- DEN bit set ($D011 bit 4)
- (raster & 7) == YSCROLL
- Raster in range $30-$F7

Cycles stolen: 15-54 (40 total)
BA signal: Goes low 3 cycles before steal
```

### Sprite DMA Timing

```
Sprite data fetch:
- Sprite 0: cycles 55-57
- Sprite 1: cycles 59-61
- Sprite 2: cycles 63-65
... (4 cycles between sprites)

Sprite pointer fetch:
- Last 16 cycles of raster line
- 2 cycles per enabled sprite
```

### API

```python
vic_dma = VicDmaEnhanced()

# Check if CPU has bus
has_bus = vic_dma.cpu_has_bus(vic_chip)

# Get steal details
info = vic_dma.steal_info(vic_chip)
# info.steal: bool
# info.kind: 'badline' | 'sprite_data' | 'sprite_ptr'
# info.ba_low: bool (BA signal state)
```

### Impact on Emulation

- Affects CPU instruction timing
- Critical for demos and timing-sensitive code
- Music players rarely affected (unless using raster IRQs)

---

## CIA Timer Edge Cases {#cia-timers}

### Implementation: cia_timer_enhanced.py

### One-Shot Mode

```
Behavior:
1. Timer counts down to 0
2. Underflow sets ICR bit
3. Timer STOPS
4. On next cycle: reload latch
5. Timer stays stopped until restarted
```

### Cascading (Timer B)

```
Timer B input modes ($0F bits 6-5):
00: phi2 clock (normal)
01: CNT pin rising edges
10: Timer A underflow
11: Timer A underflow AND CNT pin

Cascade timing:
- Timer A underflows
- Same cycle: Timer B decrements
- No delay between underflow and cascade
```

### Force Load

```
Control register bit 3:
- Sets to 1: immediately load latch -> counter
- Happens same cycle as write
- Overrides current counter value
```

### API

```python
cia = CiaEnhanced('CIA1')

# Configure timer
cia.timer_a.write_latch_lo(0x00)
cia.timer_a.write_latch_hi(0x10)
cia.timer_a.write_control(0x09)  # One-shot + start

# Step timer
underflow = cia.timer_a.step(phi2_cycles=100, cnt_pulses=0)

# Cascade Timer B from Timer A
cia.timer_b.step(
    phi2_cycles=100,
    timer_a_underflow=underflow
)
```

### Test Cases

```python
# One-shot stops and reloads
assert timer.started == False after underflow
assert timer.counter == timer.latch on next cycle

# Continuous reloads immediately
assert timer.counter == timer.latch immediately after underflow
assert timer.started == True

# Cascade timing
timer_a.step() -> underflow
assert timer_b.counter == old_value - 1 in same step
```

---

## SID Filter Non-Linearity {#sid-filter}

### Implementation: sid_filter_enhanced.py

### 6581 Resonance

```
Q values (measured from real chips):
[0] =  0.707  (no resonance)
[8] =  4.5    (noticeable)
[12] = 30.0   (extreme, self-oscillation)
[15] = 140.0  (maximum, strong oscillation)

Note: Actual values vary per chip (±30%)
```

### Cutoff Mapping

```
6581 (non-linear):
cutoff < 400:   fc = 30 * exp(cutoff/200)
400-1400:       fc = 220 + (cutoff-400)*3.78
1400-2047:      fc = 4000 + (cutoff-1400)*18.5

Range: ~30 Hz to ~16 kHz

8580 (linear):
fc = 30 + cutoff * 5.8
Range: ~30 Hz to ~12 kHz
```

### DC Offset

```
6581: ~75 mV (~0.075 normalized)
8580: ~0 mV (negligible)

Applied to input signal before filtering
```

### Filter Topology

```
State-variable filter (matches hardware):

HP = input - LP - (BP * damping)
BP += HP * w0 * dt
LP += BP * w0 * dt

where:
w0 = 2π * fc
damping = 1 / (2 * Q)
```

### API

```python
filt = create_enhanced_filter(model='6581', clock_hz=985248)

# Configure
filt.set_cutoff(0x400)  # 11-bit
filt.set_resonance(0x0C)  # 4-bit
filt.set_mode(0x10)  # LP only
filt.set_voice_routing(0x07)  # All 3 voices

# Process
output = filt.process(voice1, voice2, voice3, ext_in=0.0)

# Calibrate
filt.cutoff_offset_hz = -50.0  # Lower frequencies
filt.resonance_scale = 0.9  # Reduce Q
```

---

## Combined Waveforms {#waveforms}

### Implementation: combined_waveforms.py

### Hardware Behavior

The SID was never designed to mix waveforms. When multiple waveform bits are set, analog transistor interaction creates artifacts.

### Waveform Combinations

```
Triangle + Sawtooth (0x30):
- Sawtooth "pulls" triangle waveform
- Creates asymmetric wave
- ~20% amplitude reduction

Triangle + Pulse (0x50):
- Triangle "leaks" through pulse
- Pulse dominates but triangle visible
- Depends on pulse width

Sawtooth + Pulse (0x60):
- Creates stepped waveform
- Complex harmonic content
- Pulse width critical

All Three (0x70):
- Highly distorted
- Non-linear mixing
- ~40% amplitude reduction
```

### Table Format

```
256 waveforms * 4096 phases = 1,048,576 samples
Each sample: 12-bit (0-4095)
Total size: 2 MB uncompressed

Waveform index:
Bits 7-4: waveform select (0x1=tri, 0x2=saw, 0x4=pulse, 0x8=noise)
Phase index: bits 23-12 of phase accumulator
```

### API

```python
tables = CombinedWaveformTables(model='6581')

# Get output
output = tables.get_output(
    waveform=0x30,  # Triangle + Sawtooth
    phase_accumulator=0x123456,
    pulse_width=2048
)
# Returns: 12-bit value (0-4095)

# Load reSID tables (if available)
tables._load_resid_file('/path/to/wave6581.dat')
```

### Fallback Approximation

If reSID tables unavailable, mathematical approximation used:

```python
tri_saw_mix = (tri * 0.6 + saw * 0.4) * 0.8
tri_pulse_mix = pulse*0.9 + tri*0.1 if pulse_high else tri*0.3
saw_pulse_mix = pulse*0.7 + saw*0.3 if pulse_high else saw*0.4
```

---

## ADSR Envelope {#adsr}

### Implementation: adsr_enhanced.py

### Attack→Decay Bug

```
Bug behavior:
1. Attack reaches 255
2. State changes to Decay
3. FIRST CYCLE: envelope drops to 254 (BUG)
4. Then normal decay continues

Cause: State machine transition timing
Effect: Audible on fast attack sounds
```

### Zero-Attack Bypass

```
When attack_rate == 0:
1. Gate rises
2. Envelope instantly set to 255
3. Immediately enter Decay state
4. No rate counter used

Effect: Instant percussion sounds
```

### Exponential Decay

```
Uses 9-stage exponential table:
Stage 0-5:   Period = 30 cycles
Stage 6-11:  Period = 16 cycles
Stage 12-19: Period = 8 cycles
Stage 20-27: Period = 4 cycles
Stage 28-31: Period = 1 cycle

Creates ~exponential decay curve
```

### API

```python
adsr = create_adsr(enable_bugs=True)

# Configure
adsr.set_attack_decay(0xFF)  # Attack=15, Decay=15
adsr.set_sustain_release(0xF0)  # Sustain=15, Release=0

# Control
adsr.set_gate(True)  # Start attack

# Advance
adsr.step(cycles=100)

# Read
level = adsr.get_output()  # 0-255
state = adsr.get_state_name()  # 'Attack' | 'Decay' | 'Sustain' | 'Release'

# Disable bugs
adsr.enable_ad_bug = False
adsr.enable_zero_attack_bypass = False
```

---

## Deterministic DSP {#deterministic}

### Implementation: deterministic_components.py

### Fixed-Point Math

```
Format: 16.16 (16 integer bits, 16 fractional bits)

Convert: fixed = int(float * 65536)
Multiply: result = (a * b) >> 16
Divide: result = (a << 16) // b

Advantages:
- Exact across platforms
- No rounding variance
- Integer operations only
```

### Decimal Precision

```python
from decimal import Decimal, getcontext

getcontext().prec = 50  # 50 decimal digits

result = Decimal('440.0') * Decimal('2.0')
# Exactly 880.0 on all platforms
```

### Float Normalization

```python
# Ensure IEEE 754 double precision
value = struct.unpack('d', struct.pack('d', value))[0]
```

### API

```python
dsp = DeterministicDSP()

# Fixed-point
fixed = dsp.float_to_fixed(440.0, fractional_bits=16)
result = dsp.fixed_mul(fixed, dsp.float_to_fixed(2.0))
value = dsp.fixed_to_float(result)  # 880.0

# Decimal
value = dsp.decimal_mul(440.0, 2.0)  # Exact

# Normalize
value = dsp.normalize_float64(some_float)
```

---

## Noise LFSR {#noise}

### Implementation: deterministic_components.py (NoiseLFSREnhanced)

### Algorithm

```
23-bit LFSR with taps at bits 22 and 17:

feedback = bit_22 XOR bit_17
lfsr >>= 1
lfsr |= (feedback << 22)
output = lfsr & 0xFF
```

### Seeds

```
6581 (VICE): 0x7FFFF8
8580 (VICE): 0x7FFFFF
reSID:       0x7FFFF8
Custom:      Any 23-bit value
```

### Sequence Length

```
Maximum period: 2^23 - 1 = 8,388,607 steps
Actual period depends on seed
```

### API

```python
lfsr = NoiseLFSREnhanced(model='6581', seed=0x7FFFF8)

# Generate noise
lfsr.step()
noise = lfsr.get_output()  # 8-bit

# 12-bit for consistency with waveforms
noise_12 = lfsr.get_output_12bit()

# Get/set state (for telemetry)
state = lfsr.get_state()  # 23-bit
lfsr.set_state(state)
```

---

## Bus Persistence {#bus-persistence}

### Implementation: deterministic_components.py (BusPersistenceModel)

### Hardware Behavior

```
C64 data bus retains values due to capacitance:
- Write occurs
- Capacitors charge to data value
- Slowly discharge over time
- Read during discharge returns "floating" value

Typical decay: 7000-8000 cycles @ 25°C
Warmer temp = faster decay
```

### Color RAM

```
Color RAM is 4-bit (lower nybble)
Upper 4 bits read floating bus

Example:
Write $D800: 0x0F (white color)
Read $D800: 0xXF (where X = floating bus)
```

### Temperature Effect

```
Decay time = base_time * (1 - temp_diff * 0.015)

Examples:
20°C: ~7800 cycles
25°C: ~7424 cycles (default)
30°C: ~7050 cycles
40°C: ~6500 cycles
```

### API

```python
bus = BusPersistenceModel(persistence_cycles=7424)

# Write
bus.write(0xFF, cycle=1000)

# Read
value = bus.read(cycle=2000)  # Still 0xFF

value = bus.read(cycle=10000)  # Decayed to 0xFF (default)

# Color RAM upper bits
upper = bus.read_color_ram_upper(cycle=2000)

# Adjust for temperature
bus.set_temperature_factor(30.0)  # 30°C
```

---

## Voice 3 Output Control {#voice3}

### Implementation: deterministic_components.py (Voice3OutputControl)

### Hardware Behavior

```
$D418 bit 7: Voice 3 off
- 0: Voice 3 audio to DAC (normal)
- 1: Voice 3 audio muted

BUT:
- Oscillator still runs
- Envelope still runs
- $D41B (osc) still readable
- $D41C (env) still readable

Used for:
- Modulation without audio
- Reading oscillator for random values
```

### API

```python
v3ctrl = Voice3OutputControl()

# Set mode
v3ctrl.set_mode_register(0x8F)  # Bit 7 set = voice 3 off

# Update state (happens every cycle)
v3ctrl.update_outputs(osc=2048, env=128)

# Get audio (respects disable bit)
audio = v3ctrl.get_audio_output(raw_audio)  # 0.0 if disabled

# Read registers (always work)
osc_read = v3ctrl.read_osc()  # $D41B
env_read = v3ctrl.read_env()  # $D41C
```

---

## Test Vectors {#tests}

### Implementation: cycle_exact_tests.py

### Test Vector Format

```python
TestVector(
    name='Test_Name',
    description='What this tests',
    sid_writes=[
        (cycle, register, value),
        (100, 0x00, 0xFF),  # Write $FF to $D400 at cycle 100
        ...
    ],
    expected_output=[
        (cycle, expected_sample),
        (200, 1234),  # Expect sample value 1234 at cycle 200
        ...
    ],
    tolerance=1  # Allowed error (±1)
)
```

### Running Tests

```python
from cycle_exact_tests import CycleExactTestVectors, TestRunner

# Create emulator
emu = create_test_emulator()

# Load vectors
vectors = CycleExactTestVectors()

# Run all
runner = TestRunner(emu)
results = runner.run_all(vectors.vectors)

# Check results
print(f"Passed: {results['passed']}/{results['total']}")
for result in results['results']:
    if not result['passed']:
        print(f"FAILED: {result['name']}")
        for failure in result['failures']:
            print(f"  Cycle {failure['cycle']}: "
                  f"expected {failure['expected']}, "
                  f"got {failure['actual']}, "
                  f"error {failure['error']}")
```

### Adding New Vectors

```python
# 1. Create vector
vector = TestVector(
    name='My_Test',
    description='Tests feature X',
    sid_writes=[(0, 0x00, 0x12)],
    expected_output=[(100, 5678)],
    tolerance=10
)

# 2. Add to collection
vectors.vectors.append(vector)

# 3. Save
vectors.save_to_file('my_vectors.json')
```

---

## Performance Considerations

### Overhead by Feature

```
VIC DMA:          ~2% (per-cycle checks)
CIA Timers:       ~3% (timer updates)
SID Filter:       ~5% (filter calculations)
Combined Waves:   ~1% (table lookups)
ADSR:            ~2% (envelope updates)
Deterministic:   ~10% (fixed-point math)
Noise:           <1% (LFSR shift)
Bus Persist:     <1% (decay checks)

Total: ~25% estimated overhead for the experimental components
```

### Optimization Strategies

```python
# Disable unneeded features
config.enable_vic_dma = False  # If not running demos
config.enable_deterministic_dsp = False  # Single platform

# Use 8580 (simpler)
config.model = '8580'

# Reduce filter updates
# (Process filter every N samples instead of every sample)

# Cache waveform tables
# (Pre-compute common waveforms)
```

---

## Calibration Guide

### Per-Chip Variance

Real SID chips vary due to manufacturing tolerances. Calibrate for specific chip:

```python
# Measure cutoff frequencies from real chip
# (e.g., set cutoff=0x400, measure actual frequency)
measured_hz = 950  # Hz
expected_hz = 1000  # Hz (from formula)
offset = measured_hz - expected_hz  # -50 Hz

config.filter_cutoff_offset_hz = offset

# Measure resonance
# (e.g., set resonance=12, measure actual Q)
measured_q = 25.0
expected_q = 30.0
scale = measured_q / expected_q  # 0.833

config.filter_resonance_scale = scale
```

### Temperature Calibration

```python
# Measure bus persistence at operating temperature
# (Use test program that reads color RAM upper bits)
measured_cycles = 6800
config.bus_persist_cycles = measured_cycles

# Or set temperature
config.temperature_celsius = 32.0  # Auto-adjusts
```

---

**End of Technical Specification**
