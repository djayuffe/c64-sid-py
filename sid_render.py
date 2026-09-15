#!/usr/bin/env python3
"""Render a .sid (PSID/RSID) to WAV using the standalone Python port.

Usage:
  python3 sid_render.py input.sid output.wav --seconds 30 --rate 44100

Notes:
  - For RSID tunes without ROMs, pass --hle to use built-in minimal HVL stubs.
  - If you have ROMs, pass --kernal / --basic / --chargen for higher compatibility.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from c64sid.logger import SystemLogger
from c64sid.sid.playback import PlaybackCoordinator
from c64sid.sid.sid_types import C64Config, RomPack


def read_file(p: str) -> bytes:
    try:
        return Path(p).read_bytes()
    except FileNotFoundError:
        print(f"Error: File not found: {p}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permission denied: {p}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading {p}: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('input_sid')
    ap.add_argument('output_wav')
    ap.add_argument('--seconds', type=float, default=10.0)
    ap.add_argument('--rate', type=int, default=44100)
    ap.add_argument('--hle', action='store_true', help='Use built-in HLE ROM stubs (recommended for RSID if ROMs missing)')
    ap.add_argument('--kernal', type=str, default='')
    ap.add_argument('--basic', type=str, default='')
    ap.add_argument('--chargen', type=str, default='')
    ap.add_argument('--dump-sidpro', type=str, default='', help='Write SID-PRO Forensic Export (V6) JSON to this path')
    ap.add_argument('--sidpro-no-compress', action='store_true', help='Disable zlib compression inside .sidpro export')
    ap.add_argument('--sidpro-telemetry-rate', type=int, default=1, help='Capture telemetry every N frames (1=every frame)')
    ap.add_argument('--no-sidpro-verbose-sid', action='store_true', help='Disable verbose SID silicon telemetry fields (enabled by default)')
    ap.add_argument('--no-sidpro-io-trace', action='store_true', help='Disable I/O write trace capture (enabled by default)')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    if args.quiet:
        SystemLogger.set_enabled(False)

    cfg = C64Config()
    # Explicit ROMs take precedence; --hle remains an explicit fallback.
    cfg.enableHle = bool(args.hle) or not bool(args.kernal or args.basic or args.chargen)

    if not cfg.enableHle and (args.kernal or args.basic or args.chargen):
        cfg.roms = RomPack(
            kernal=read_file(args.kernal) if args.kernal else None,
            basic=read_file(args.basic) if args.basic else None,
            chargen=read_file(args.chargen) if args.chargen else None,
        )

    raw = read_file(args.input_sid)
    pb = PlaybackCoordinator(cfg)

    if args.dump_sidpro:
        pb.enable_sidpro_export(
            args.dump_sidpro,
            compress=(not bool(args.sidpro_no_compress)),
            telemetry_rate=int(args.sidpro_telemetry_rate),
            verbose_sid=not bool(args.no_sidpro_verbose_sid),
            io_trace=not bool(args.no_sidpro_io_trace),
        )

    pb.load_sid_bytes(raw)
    res = pb.render_to_wav(args.output_wav, seconds=args.seconds, sample_rate=args.rate)

    SystemLogger.log('CLI', f"Wrote {res.wav_path} | rendered play calls: {res.frames_rendered} | samples: {res.samples}", 'info')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
