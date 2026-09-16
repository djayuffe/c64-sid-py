from __future__ import annotations

import base64
import json
import time
import zlib
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List


SIDPRO_VERSION = "SID-PRO-FORENSIC-V6"


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(s: str) -> bytes:
    if not s:
        return b""
    return base64.b64decode(s.encode("ascii"))


@dataclass
class SIDProForensicExport:
    """SID-PRO Forensic Export (V6).

    Heavy blobs live under `binary.*.data` as Base64, optionally zlib-compressed.

    This class also stores raw (decoded) blobs internally to:
      - compute checksums
      - validate stream size invariants
      - allow roundtrip load/validate
    """

    metadata: Dict[str, Any] = field(default_factory=dict)
    binary: Dict[str, Any] = field(default_factory=dict)
    telemetry: Dict[str, Any] = field(default_factory=lambda: {"frame_rate": 50.0, "frames": []})
    analysis: Dict[str, Any] = field(default_factory=dict)

    # Raw internal blobs (decoded)
    _bus_cycles_raw: bytes = field(default=b"", repr=False)
    _bus_events_raw: bytes = field(default=b"", repr=False)
    _io_cycles_raw: bytes = field(default=b"", repr=False)
    _io_events_raw: bytes = field(default=b"", repr=False)
    _ram_initial_raw: bytes = field(default=b"", repr=False)
    _ram_final_raw: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if not self.metadata:
            self.metadata = {
                "version": SIDPRO_VERSION,
                "timestamp_ms": int(time.time() * 1000),
                "module": {"title": "", "author": "", "released": ""},
                "config": {},
                "compression": "zlib",
                "checksums": {},
                "extensions": {},
            }

        if not self.binary:
            self.binary = {
                "bus_cycles": {"encoding": "float64le", "count": 0, "compress": "zlib", "data": ""},
                "bus_events": {"encoding": "u8_triplets", "count": 0, "compress": "zlib", "data": ""},
                "ram_initial": {"encoding": "u8", "count": 0, "compress": "zlib", "data": ""},
                "ram_final": {"encoding": "u8", "count": 0, "compress": "zlib", "data": ""},
                # Optional extension: all I/O writes (cycle_f64 + [addr_u16,value_u8])
                "io_cycles": {"encoding": "float64le", "count": 0, "compress": "zlib", "data": ""},
                "io_events": {"encoding": "u16le_u8_triplets", "count": 0, "compress": "zlib", "data": ""},
            }

        # Ensure checksum dict exists
        self.metadata.setdefault("checksums", {})

    # -----------------
    # Build / Fill
    # -----------------
    def set_metadata_config(
        self,
        *,
        title: str,
        author: str,
        released: str,
        clock_hz: int,
        standard: str,
        sid_count: int,
        sid_models: List[str],
        sid_bases: List[int],
        sample_rate: int,
        frame_rate: float,
        song: int,
        compression: str = "zlib",
    ) -> None:
        self.metadata["version"] = SIDPRO_VERSION
        self.metadata["timestamp_ms"] = int(time.time() * 1000)
        self.metadata["module"] = {"title": str(title), "author": str(author), "released": str(released)}
        self.metadata["config"] = {
            "clock_hz": int(clock_hz),
            "standard": str(standard),
            "sid_count": int(sid_count),
            "sid_models": [str(x) for x in (sid_models or [])],
            "sid_bases": [int(x) for x in (sid_bases or [])],
            "sample_rate": int(sample_rate),
            "frame_rate": float(frame_rate),
            "song": int(song),
        }
        self.metadata["compression"] = str(compression)
        self.telemetry["frame_rate"] = float(frame_rate)

    def set_bus_stream(self, *, cycles_f64: bytes, events_u8: bytes) -> None:
        self._bus_cycles_raw = bytes(cycles_f64)
        self._bus_events_raw = bytes(events_u8)
        self.metadata["checksums"]["bus_cycles"] = _sha256_hex(self._bus_cycles_raw)
        self.metadata["checksums"]["bus_events"] = _sha256_hex(self._bus_events_raw)

    def set_io_stream(self, *, cycles_f64: bytes, events_u8: bytes) -> None:
        self._io_cycles_raw = bytes(cycles_f64)
        self._io_events_raw = bytes(events_u8)
        self.metadata["extensions"].setdefault("io_trace", True)
        self.metadata["checksums"]["io_cycles"] = _sha256_hex(self._io_cycles_raw)
        self.metadata["checksums"]["io_events"] = _sha256_hex(self._io_events_raw)

    def set_ram_snapshots(self, *, ram_initial: bytes, ram_final: bytes) -> None:
        self._ram_initial_raw = bytes(ram_initial)
        self._ram_final_raw = bytes(ram_final)
        self.metadata["checksums"]["ram_initial"] = _sha256_hex(self._ram_initial_raw)
        self.metadata["checksums"]["ram_final"] = _sha256_hex(self._ram_final_raw)

    def add_telemetry_frame(self, frame: Dict[str, Any]) -> None:
        self.telemetry.setdefault("frames", []).append(frame)

    # -----------------
    # Serialization helpers
    # -----------------
    @staticmethod
    def _encode_blob(raw: bytes, *, compress: bool) -> Dict[str, Any]:
        out = bytes(raw)
        if compress and out:
            out = zlib.compress(out, level=9)
            return {"compress": "zlib", "data": _b64e(out)}
        return {"compress": "none", "data": _b64e(out)}

    @staticmethod
    def _decode_blob(blob: Dict[str, Any]) -> bytes:
        raw = _b64d(str(blob.get("data", "")))
        comp = str(blob.get("compress", "none")).lower()
        if comp == "zlib" and raw:
            return zlib.decompress(raw)
        return raw

    def export_to_dict(self, *, compress: bool = True) -> Dict[str, Any]:
        # Decide per-export compression marker
        self.metadata["compression"] = "zlib" if compress else "none"

        # Encode blobs
        self.binary["bus_cycles"].update(self._encode_blob(self._bus_cycles_raw, compress=compress))
        self.binary["bus_events"].update(self._encode_blob(self._bus_events_raw, compress=compress))
        self.binary["ram_initial"].update(self._encode_blob(self._ram_initial_raw, compress=compress))
        self.binary["ram_final"].update(self._encode_blob(self._ram_final_raw, compress=compress))

        self.binary["bus_cycles"]["encoding"] = "float64le"
        self.binary["bus_events"]["encoding"] = "u8_triplets"
        self.binary["ram_initial"]["encoding"] = "u8"
        self.binary["ram_final"]["encoding"] = "u8"

        self.binary["bus_cycles"]["count"] = len(self._bus_cycles_raw) // 8
        self.binary["bus_events"]["count"] = len(self._bus_events_raw) // 3
        self.binary["ram_initial"]["count"] = len(self._ram_initial_raw)
        self.binary["ram_final"]["count"] = len(self._ram_final_raw)

        # Optional IO trace
        if self._io_cycles_raw or self._io_events_raw:
            self.binary["io_cycles"].update(self._encode_blob(self._io_cycles_raw, compress=compress))
            self.binary["io_events"].update(self._encode_blob(self._io_events_raw, compress=compress))
            self.binary["io_cycles"]["encoding"] = "float64le"
            self.binary["io_events"]["encoding"] = "u16le_u8_triplets"
            self.binary["io_cycles"]["count"] = len(self._io_cycles_raw) // 8
            self.binary["io_events"]["count"] = len(self._io_events_raw) // 3
        else:
            # Keep stable keys but empty
            self.binary["io_cycles"].update({"compress": "none", "data": ""})
            self.binary["io_events"].update({"compress": "none", "data": ""})
            self.binary["io_cycles"]["count"] = 0
            self.binary["io_events"]["count"] = 0

        return {
            "metadata": self.metadata,
            "binary": self.binary,
            "telemetry": self.telemetry,
            "analysis": self.analysis,
        }

    def export_to_file(self, path: str, *, compress: bool = True) -> None:
        payload = self.export_to_dict(compress=compress)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))

    # -----------------
    # Load / Validate
    # -----------------
    @classmethod
    def load_from_file(cls, path: str) -> "SIDProForensicExport":
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)

        exp = cls()
        exp.metadata = obj.get("metadata", {}) or {}
        exp.binary = obj.get("binary", {}) or {}
        exp.telemetry = obj.get("telemetry", {}) or {}
        exp.analysis = obj.get("analysis", {}) or {}

        b = exp.binary
        exp._bus_cycles_raw = exp._decode_blob(b.get("bus_cycles", {}))
        exp._bus_events_raw = exp._decode_blob(b.get("bus_events", {}))
        exp._ram_initial_raw = exp._decode_blob(b.get("ram_initial", {}))
        exp._ram_final_raw = exp._decode_blob(b.get("ram_final", {}))

        # Optional IO trace
        exp._io_cycles_raw = exp._decode_blob(b.get("io_cycles", {}))
        exp._io_events_raw = exp._decode_blob(b.get("io_events", {}))

        return exp

    def validate(self) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        # version
        if (self.metadata.get("version") != SIDPRO_VERSION):
            errors.append(f"metadata.version must be {SIDPRO_VERSION}")

        cfg = self.metadata.get("config") or {}
        for k in ("clock_hz", "standard", "sid_count", "sid_models", "sid_bases", "sample_rate", "frame_rate", "song"):
            if k not in cfg:
                errors.append(f"metadata.config missing required field: {k}")

        # RAM sizes
        if self._ram_initial_raw and len(self._ram_initial_raw) != 65536:
            errors.append(f"ram_initial must be 65536 bytes, got {len(self._ram_initial_raw)}")
        if self._ram_final_raw and len(self._ram_final_raw) != 65536:
            errors.append(f"ram_final must be 65536 bytes, got {len(self._ram_final_raw)}")

        # Bus stream sizes
        if len(self._bus_events_raw) % 3 != 0:
            errors.append("bus_events length must be multiple of 3")
        if len(self._bus_cycles_raw) % 8 != 0:
            errors.append("bus_cycles length must be multiple of 8 (float64)")
        ev_count = len(self._bus_events_raw) // 3
        cy_count = len(self._bus_cycles_raw) // 8
        if ev_count != cy_count:
            errors.append(f"bus_cycles count ({cy_count}) must equal bus_events count ({ev_count})")

        if ev_count == 0:
            warnings.append("bus stream is empty (no SID register writes captured)")

        # IO stream sizes (optional)
        if self._io_cycles_raw or self._io_events_raw:
            if len(self._io_events_raw) % 3 != 0:
                errors.append("io_events length must be multiple of 3 (addr_u16le + value_u8)")
            if len(self._io_cycles_raw) % 8 != 0:
                errors.append("io_cycles length must be multiple of 8 (float64)")
            ioev = len(self._io_events_raw) // 3
            iocy = len(self._io_cycles_raw) // 8
            if ioev != iocy:
                errors.append(f"io_cycles count ({iocy}) must equal io_events count ({ioev})")

        # Checksums
        chk = (self.metadata.get("checksums") or {})
        if chk:
            def _chk(name: str, raw: bytes) -> None:
                expected = chk.get(name)
                if expected and expected != _sha256_hex(raw):
                    errors.append(f"{name} checksum mismatch")

            _chk("bus_cycles", self._bus_cycles_raw)
            _chk("bus_events", self._bus_events_raw)
            _chk("ram_initial", self._ram_initial_raw)
            _chk("ram_final", self._ram_final_raw)
            if self._io_cycles_raw or self._io_events_raw:
                _chk("io_cycles", self._io_cycles_raw)
                _chk("io_events", self._io_events_raw)

        # Telemetry sanity
        frames = (self.telemetry.get("frames") or [])
        if not isinstance(frames, list):
            errors.append("telemetry.frames must be a list")

        return {
            "ok": (len(errors) == 0),
            "errors": errors,
            "warnings": warnings,
            "stats": self.get_statistics(),
        }

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "bus_events": len(self._bus_events_raw) // 3,
            "io_events": len(self._io_events_raw) // 3,
            "ram_initial_bytes": len(self._ram_initial_raw),
            "ram_final_bytes": len(self._ram_final_raw),
            "telemetry_frames": len((self.telemetry.get("frames") or [])),
        }
