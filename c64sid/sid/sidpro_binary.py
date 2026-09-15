"""SID-PRO Binary Format V6.1 (.sidprob) with delta compression and streaming."""
from __future__ import annotations

import base64
import json
import struct
import zlib
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, List, Optional

from .varint import encode_varint, decode_varint, encode_varint_signed, decode_varint_signed

MAGIC = b"SIDPRO\x06\x01"  # V6.1
CHUNK_HEADER = 0x01
CHUNK_BUS_EVENTS = 0x02
CHUNK_TELEMETRY = 0x03
CHUNK_RAM = 0x04
CHUNK_ANALYSIS = 0x05
CHUNK_IO_EVENTS = 0x06
CHUNK_EOF = 0xFF


def _crc32(data: bytes) -> int:
    """Calculate CRC32 checksum."""
    return zlib.crc32(data) & 0xFFFFFFFF


@dataclass
class BusEvent:
    """Single bus event with delta encoding."""
    cycle_delta: int  # VarInt
    chip: int  # 0-3
    register: int  # 0-28
    value: int  # 0-255
    is_delta: bool  # Value is delta vs absolute


class DeltaEncoder:
    """Delta encoder for bus events."""

    def __init__(self):
        self.last_cycle = 0.0
        self.last_values = {}  # (chip, reg) -> value

    def encode_event(self, cycle: float, chip: int, register: int, value: int) -> bytes:
        """Encode a single bus event with delta compression."""
        # Cycle delta
        cycle_delta = int(cycle - self.last_cycle)
        self.last_cycle = cycle

        # Value delta
        key = (chip, register)
        last_val = self.last_values.get(key, 0)
        val_delta = value - last_val
        self.last_values[key] = value

        # Encode
        result = bytearray()
        result.extend(encode_varint(cycle_delta))

        # Control byte: [is_delta:1][chip:2][register:5]
        is_delta = -64 <= val_delta <= 63
        control = (chip & 0x03) << 5 | (register & 0x1F)
        if is_delta:
            control |= 0x80
        result.append(control)

        # Value
        if is_delta:
            result.append((val_delta + 128) & 0xFF)  # Offset to unsigned
        else:
            result.append(value & 0xFF)

        return bytes(result)

    def reset(self):
        """Reset encoder state."""
        self.last_cycle = 0.0
        self.last_values.clear()


class DeltaDecoder:
    """Delta decoder for bus events."""

    def __init__(self):
        self.last_values = {}
        self.current_cycle = 0.0

    def decode_event(self, data: bytes, offset: int) -> tuple[tuple[float, int, int, int], int]:
        """Decode event, returns ((cycle, chip, reg, val), bytes_consumed)."""
        pos = offset

        # Cycle delta
        cycle_delta, consumed = decode_varint(data, pos)
        pos += consumed
        self.current_cycle += cycle_delta

        # Control byte
        control = data[pos]
        pos += 1

        is_delta = bool(control & 0x80)
        chip = (control >> 5) & 0x03
        register = control & 0x1F

        # Value
        val_byte = data[pos]
        pos += 1

        key = (chip, register)
        if is_delta:
            delta = val_byte - 128
            value = (self.last_values.get(key, 0) + delta) & 0xFF
        else:
            value = val_byte

        self.last_values[key] = value

        return (self.current_cycle, chip, register, value), pos - offset


class BinaryWriter:
    """Write SID-PRO binary format with chunking."""

    def __init__(self, f: BinaryIO):
        self.f = f
        self.f.write(MAGIC)

    def write_chunk(self, chunk_type: int, data: bytes, compress: bool = True):
        """Write a chunk with optional compression and CRC."""
        payload = data
        flags = 0

        if compress and len(data) > 100:
            compressed = zlib.compress(data, level=9)
            if len(compressed) < len(data):
                payload = compressed
                flags |= 0x01  # Compressed flag

        crc = _crc32(payload)

        # Chunk header: [type:1][flags:1][length:4][crc:4][data]
        header = struct.pack('<BBII', chunk_type, flags, len(payload), crc)
        self.f.write(header)
        self.f.write(payload)

    def write_header(self, metadata: Dict[str, Any]):
        """Write header chunk with metadata."""
        import json
        data = json.dumps(metadata, separators=(',', ':')).encode('utf-8')
        self.write_chunk(CHUNK_HEADER, data, compress=False)

    def write_bus_events_delta(self, events: List[tuple[float, int, int, int]]):
        """Write bus events with delta compression."""
        encoder = DeltaEncoder()
        data = bytearray()

        # Event count
        data.extend(encode_varint(len(events)))

        # Encode events
        for cycle, chip, reg, val in events:
            data.extend(encoder.encode_event(cycle, chip, reg, val))

        self.write_chunk(CHUNK_BUS_EVENTS, bytes(data), compress=True)

    def write_telemetry(self, frames: List[Dict[str, Any]]):
        """Write telemetry frames."""
        import json
        data = json.dumps(frames, separators=(',', ':')).encode('utf-8')
        self.write_chunk(CHUNK_TELEMETRY, data, compress=True)

    def write_ram(self, ram_data: bytes):
        """Write RAM snapshot."""
        self.write_chunk(CHUNK_RAM, ram_data, compress=True)

    def write_io_events(self, events: List[tuple[float, int, int]]):
        """Write I/O events (cycle, addr, value)."""
        encoder = DeltaEncoder()
        data = bytearray()
        data.extend(encode_varint(len(events)))

        for cycle, addr, val in events:
            data.extend(encode_varint(int(cycle - encoder.last_cycle)))
            encoder.last_cycle = cycle
            data.extend(struct.pack('<HB', addr, val))

        self.write_chunk(CHUNK_IO_EVENTS, bytes(data), compress=True)

    def write_eof(self):
        """Write end-of-file marker."""
        self.write_chunk(CHUNK_EOF, b'', compress=False)


class BinaryReader:
    """Read SID-PRO binary format."""

    def __init__(self, f: BinaryIO):
        self.f = f
        magic = f.read(8)
        if magic != MAGIC:
            raise ValueError(f"Invalid magic number: {magic!r}")

    def read_chunk(self) -> Optional[tuple[int, bytes]]:
        """Read next chunk, returns (type, data) or None if EOF."""
        header = self.f.read(10)
        if len(header) < 10:
            return None

        chunk_type, flags, length, expected_crc = struct.unpack('<BBII', header)

        if chunk_type == CHUNK_EOF:
            return (CHUNK_EOF, b'')

        payload = self.f.read(length)
        if len(payload) != length:
            raise ValueError(f"Truncated chunk: expected {length}, got {len(payload)}")

        # Verify CRC
        actual_crc = _crc32(payload)
        if actual_crc != expected_crc:
            raise ValueError(f"CRC mismatch: expected {expected_crc:08x}, got {actual_crc:08x}")

        # Decompress if needed
        if flags & 0x01:
            payload = zlib.decompress(payload)

        return (chunk_type, payload)

    def read_all_chunks(self) -> Dict[int, List[bytes]]:
        """Read all chunks into dictionary."""
        chunks = {}
        while True:
            result = self.read_chunk()
            if result is None or result[0] == CHUNK_EOF:
                break
            chunk_type, data = result
            chunks.setdefault(chunk_type, []).append(data)
        return chunks

    def decode_bus_events(self, data: bytes) -> List[tuple[float, int, int, int]]:
        """Decode delta-compressed bus events."""
        decoder = DeltaDecoder()
        events = []

        # Read count
        count, pos = decode_varint(data, 0)

        # Decode events
        for _ in range(count):
            event, consumed = decoder.decode_event(data, pos)
            events.append(event)
            pos += consumed

        return events

    def decode_io_events(self, data: bytes) -> List[tuple[float, int, int]]:
        """Decode delta-compressed I/O events."""
        count, pos = decode_varint(data, 0)
        cycle = 0.0
        events: List[tuple[float, int, int]] = []
        for _ in range(count):
            delta, consumed = decode_varint(data, pos)
            pos += consumed
            if pos + 3 > len(data):
                raise ValueError('Truncated I/O event stream')
            addr, value = struct.unpack_from('<HB', data, pos)
            pos += 3
            cycle += delta
            events.append((cycle, addr, value))
        if pos != len(data):
            raise ValueError('Trailing bytes in I/O event stream')
        return events


class StreamingWriter:
    """Streaming writer for very long captures."""

    def __init__(self, path: str, metadata: Dict[str, Any], buffer_size: int = 10000):
        self.path = path
        self.f = open(path, 'wb')
        self.writer = BinaryWriter(self.f)
        self.writer.write_header(metadata)

        self.bus_buffer: List[tuple[float, int, int, int]] = []
        self.telemetry_buffer: List[Dict[str, Any]] = []
        self.buffer_size = buffer_size

    def add_bus_event(self, cycle: float, chip: int, register: int, value: int):
        """Add bus event, auto-flush if buffer full."""
        self.bus_buffer.append((cycle, chip, register, value))
        if len(self.bus_buffer) >= self.buffer_size:
            self.flush_bus()

    def add_telemetry(self, frame: Dict[str, Any]):
        """Add telemetry frame, auto-flush if buffer full."""
        self.telemetry_buffer.append(frame)
        if len(self.telemetry_buffer) >= 100:
            self.flush_telemetry()

    def flush_bus(self):
        """Flush bus event buffer."""
        if self.bus_buffer:
            self.writer.write_bus_events_delta(self.bus_buffer)
            self.bus_buffer.clear()

    def flush_telemetry(self):
        """Flush telemetry buffer."""
        if self.telemetry_buffer:
            self.writer.write_telemetry(self.telemetry_buffer)
            self.telemetry_buffer.clear()

    def write_ram(self, ram_data: bytes):
        """Write RAM snapshot."""
        self.writer.write_ram(ram_data)

    def finalize(self):
        """Flush all buffers and close file."""
        self.flush_bus()
        self.flush_telemetry()
        self.writer.write_eof()
        self.f.close()


def _decode_forensic_blob(blob: Dict[str, Any]) -> bytes:
    """Decode one SID-PRO JSON blob without depending on private export state."""
    data = str(blob.get('data', ''))
    if not data:
        return b''
    raw = base64.b64decode(data.encode('ascii'))
    if str(blob.get('compress', 'none')).lower() == 'zlib':
        return zlib.decompress(raw)
    return raw


def _pack_f64(values: List[float]) -> bytes:
    return struct.pack(f'<{len(values)}d', *values) if values else b''


def export_to_binary(export_dict: Dict[str, Any], path: str):
    """Export SID-PRO data to binary format."""
    with open(path, 'wb') as f:
        writer = BinaryWriter(f)

        # Header
        writer.write_header(export_dict.get('metadata', {}))

        binary = export_dict.get('binary', {}) or {}
        cycles_raw = _decode_forensic_blob(binary.get('bus_cycles', {}))
        events_raw = _decode_forensic_blob(binary.get('bus_events', {}))
        if len(cycles_raw) % 8 or len(events_raw) % 3:
            raise ValueError('Invalid SID-PRO bus stream lengths')
        count = len(cycles_raw) // 8
        if count != len(events_raw) // 3:
            raise ValueError('SID-PRO bus cycle/event counts differ')
        if count:
            cycles = struct.unpack(f'<{count}d', cycles_raw)
            writer.write_bus_events_delta([
                (cycles[i], events_raw[i * 3], events_raw[i * 3 + 1], events_raw[i * 3 + 2])
                for i in range(count)
            ])

        frames = (export_dict.get('telemetry', {}) or {}).get('frames', [])
        if frames:
            writer.write_telemetry(frames)

        for key in ('ram_initial', 'ram_final'):
            ram = _decode_forensic_blob(binary.get(key, {}))
            if ram:
                writer.write_ram(ram)

        analysis = export_dict.get('analysis', {}) or {}
        if analysis:
            writer.write_chunk(CHUNK_ANALYSIS, json.dumps(analysis, separators=(',', ':')).encode('utf-8'))

        io_cycles_raw = _decode_forensic_blob(binary.get('io_cycles', {}))
        io_events_raw = _decode_forensic_blob(binary.get('io_events', {}))
        if len(io_cycles_raw) % 8 or len(io_events_raw) % 3:
            raise ValueError('Invalid SID-PRO I/O stream lengths')
        io_count = len(io_cycles_raw) // 8
        if io_count != len(io_events_raw) // 3:
            raise ValueError('SID-PRO I/O cycle/event counts differ')
        if io_count:
            io_cycles = struct.unpack(f'<{io_count}d', io_cycles_raw)
            writer.write_io_events([
                (io_cycles[i], *struct.unpack_from('<HB', io_events_raw, i * 3))
                for i in range(io_count)
            ])

        # EOF
        writer.write_eof()


def load_from_binary(path: str) -> Dict[str, Any]:
    """Load SID-PRO binary format."""
    with open(path, 'rb') as f:
        reader = BinaryReader(f)
        chunks = reader.read_all_chunks()

        # Parse chunks
        import json
        result = {'metadata': {}, 'binary': {}, 'telemetry': {'frames': []}, 'analysis': {}}

        # Header
        if CHUNK_HEADER in chunks:
            result['metadata'] = json.loads(chunks[CHUNK_HEADER][0].decode('utf-8'))

        # Bus events
        if CHUNK_BUS_EVENTS in chunks:
            all_events = []
            for chunk_data in chunks[CHUNK_BUS_EVENTS]:
                all_events.extend(reader.decode_bus_events(chunk_data))
            result['_bus_events_decoded'] = all_events
            result['binary']['bus_events'] = all_events

        # Telemetry
        if CHUNK_TELEMETRY in chunks:
            for chunk_data in chunks[CHUNK_TELEMETRY]:
                frames = json.loads(chunk_data.decode('utf-8'))
                result['telemetry']['frames'].extend(frames)

        if CHUNK_RAM in chunks:
            rams = chunks[CHUNK_RAM]
            result['binary']['ram_initial'] = rams[0]
            if len(rams) > 1:
                result['binary']['ram_final'] = rams[1]

        if CHUNK_ANALYSIS in chunks:
            result['analysis'] = json.loads(chunks[CHUNK_ANALYSIS][0].decode('utf-8'))

        if CHUNK_IO_EVENTS in chunks:
            all_io_events = []
            for chunk_data in chunks[CHUNK_IO_EVENTS]:
                all_io_events.extend(reader.decode_io_events(chunk_data))
            result['_io_events_decoded'] = all_io_events
            result['binary']['io_events'] = all_io_events

        return result
