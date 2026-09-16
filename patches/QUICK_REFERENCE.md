# Experimental wrapper quick reference

Requires Python 3.10+.

```python
from patches import EnhancedEmulatorConfig, EnhancedEmulator

config = EnhancedEmulatorConfig()
config.model = '8580'
config.enable_combined_waveforms = True
config.enable_adsr_pipeline = True
config.noise_lfsr_seed = 0x7FFFFF

sid = EnhancedEmulator(config)
sid.write_register(0x04, 0x21)
sid.step(1000)
sample_i16 = sid.get_sample()
```

For more than one SID, set `config.num_chips` to 2 or 3 and select a chip with
`write_register(register, value, chip=index)`.

```bash
python3 patches/verify_installation.py
```

This verifies wrapper behavior only. It does not certify C64 timing or real SID
hardware compatibility.
