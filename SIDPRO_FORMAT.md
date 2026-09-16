# SID-PRO format

SID-PRO is this project's forensic-capture format. It stores data produced by
this emulator; it is not an interchange standard and does not establish
cycle-exact or hardware-perfect replay.

## JSON (`.sidpro`)

`SIDProForensicExport` serializes a JSON object with:

- `metadata`: version, module fields, emulator configuration, and checksums.
- `binary`: Base64 blobs for bus cycles, SID register-event triples, optional
  I/O events, and initial/final RAM snapshots. Blobs may use zlib.
- `telemetry.frames`: periodic SID snapshots.
- `analysis`: optional heuristic analysis.

Create captures through the renderer:

```bash
c64sid-render music.sid output.wav --dump-sidpro capture.sidpro
```

Load and validate one:

```python
from c64sid.sid.sidpro_forensic import SIDProForensicExport

capture = SIDProForensicExport.load_from_file('capture.sidpro')
validation = capture.validate()
if not validation['ok']:
    raise ValueError(validation['errors'])
```

## Binary (`.sidprob`)

The binary companion format begins with `SIDPRO\\x06\\x01`, followed by chunks:

| Type | Meaning |
| --- | --- |
| `0x01` | JSON metadata |
| `0x02` | delta-compressed SID events |
| `0x03` | telemetry frames |
| `0x04` | RAM snapshot |
| `0x05` | analysis JSON |
| `0x06` | delta-compressed I/O events |
| `0xff` | mandatory EOF |

Each chunk stores a CRC32 of its stored payload. Readers reject truncated
headers, malformed EOF chunks, unknown flags, CRC failures, invalid compressed
payloads, trailing bytes, and streams without EOF.

```python
from c64sid.sid.sidpro_binary import export_to_binary, load_from_binary

export_to_binary(capture.export_to_dict(), 'capture.sidprob')
decoded = load_from_binary('capture.sidprob')
```

For incremental binary writing:

```python
from c64sid.sid.sidpro_binary import StreamingWriter

writer = StreamingWriter('capture.sidprob', metadata)
writer.add_bus_event(cycle, chip, register, value)
writer.add_telemetry(frame)
writer.finalize()
```

Binary event cycles must be supplied in non-decreasing order.
