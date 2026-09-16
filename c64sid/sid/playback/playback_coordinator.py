from __future__ import annotations

import wave
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

from array import array

from ...logger import SystemLogger
from ..c64_system import C64System
from ..hle import HLE
from ..sid_chip import SidChip
from ..sid_parser import parse_sid_header
from ..sid_types import C64Config, SidHeader
from ..sidpro_forensic import SIDProForensicExport
from ..sidpro_recorder import SidProRecorder, IoProRecorder


def _i16(x: float) -> int:
    if x < -1.0: x = -1.0
    if x > 1.0: x = 1.0
    return int(round(x * 32767.0))


@dataclass
class PlaybackResult:
    wav_path: str
    frames_rendered: int
    samples: int


class PlaybackCoordinator:
    """Standalone coordinator that loads a SID file and renders PCM audio.

    - Runs the C64 core for init + play calls (VBI style)
    - Generates WAV at target sample_rate

    Notes:
    - For RSID tunes requiring ROMs, enableHle=True provides minimal stubs.
    """

    def __init__(self, cfg: Optional[C64Config] = None):
        self.cfg = cfg or C64Config()
        self.c64 = C64System(self.cfg)
        self.header: Optional[SidHeader] = None
        self.sid_data: Optional[bytes] = None
        self.song: Optional[int] = None

        # SID-PRO forensic export (optional)
        self._sidpro_path: Optional[str] = None
        self._sidpro_compress: bool = True
        self._sidpro_telemetry_div: int = 1
        self._sidpro_verbose_sid: bool = True
        self._sidpro_io_trace: bool = True
        self._iopro_recorder: Optional[IoProRecorder] = None
        self._sidpro_export: Optional[SIDProForensicExport] = None
        self._sidpro_recorder: Optional[SidProRecorder] = None

    def enable_sidpro_export(self, path: str, *, compress: bool = True, telemetry_rate: int = 1, verbose_sid: bool = True, io_trace: bool = True) -> None:
        """Enable SID-PRO forensic export (.sidpro JSON).

        telemetry_rate:
            1 => capture telemetry every frame (50/60Hz)
            2 => every 2nd frame, etc.
        """
        if not str(path):
            raise ValueError('SID-PRO output path must not be empty')
        if isinstance(telemetry_rate, bool) or not isinstance(telemetry_rate, int) or telemetry_rate < 1:
            raise ValueError('SID-PRO telemetry rate must be a positive integer')

        self._sidpro_path = str(path)
        self._sidpro_compress = bool(compress)
        self._sidpro_telemetry_div = int(telemetry_rate)
        self._sidpro_verbose_sid = bool(verbose_sid)
        self._sidpro_io_trace = bool(io_trace)

    def load_sid_bytes(self, raw: bytes, *, song: Optional[int] = None) -> None:
        """Load a SID file and initialize the selected one-based subsong.

        When ``song`` is omitted, the file's declared start song is used.
        """
        hdr, mem = parse_sid_header(raw)
        selected_song = hdr.startSong if song is None else int(song)
        if not 1 <= selected_song <= hdr.songs:
            raise ValueError(f'Song {selected_song} is outside the valid range 1-{hdr.songs}')

        # A coordinator can be reused. Detach an old capture before resetting the
        # machine so a subsequent load never writes into a stale export.
        self.c64.memory.uninstall_sidpro()
        self.c64.memory.uninstall_iopro()
        self._iopro_recorder = None
        self._sidpro_export = None
        self._sidpro_recorder = None
        self.header = hdr
        self.sid_data = mem
        self.song = selected_song

        SystemLogger.log('Playback', f"Loaded '{hdr.title}' by {hdr.author} ({hdr.released})", 'info')
        SystemLogger.log('Playback', f"System: {'NTSC' if hdr.isNtsc else 'PAL'} | SIDs: {hdr.sidCount} | BASIC: {hdr.c64BasicFlag}", 'info')

        # Setup machine
        self.c64.set_model(hdr.isNtsc)

        # Install ROMs
        if self.cfg.enableHle:
            self.c64.memory.install_roms(HLE.generate_basic(), HLE.generate_kernal(), None)
        else:
            self.c64.memory.install_roms(self.cfg.roms.basic, self.cfg.roms.kernal, self.cfg.roms.chargen)

        # Attach SIDs
        sids = []
        for i in range(hdr.sidCount):
            sid = SidChip(hdr.clockFreq, self.cfg)
            sid.set_model(hdr.sidModels[i])
            sids.append(sid)
        self.c64.attach_sids(sids, hdr.sidAddresses)

        # Reset all machine state after installing the ROMs and chips, then load
        # the tune into the fresh RAM image. Reusing a coordinator must not leak
        # RAM, peripheral, SID, bus, or interrupt state from a previous tune.
        self.c64.reset()
        self.c64.load_program(hdr.loadAddress, mem)

        # SID-PRO: install bus recorder *before* init so we capture all SID writes
        if self._sidpro_path:
            self._sidpro_export = SIDProForensicExport()
            self._sidpro_recorder = SidProRecorder()
            self.c64.memory.install_sidpro(self._sidpro_recorder, lambda: float(self.c64.cpu.current_bus_cycle))
            if self._sidpro_io_trace:
                self._iopro_recorder = IoProRecorder()
                self.c64.memory.install_iopro(self._iopro_recorder, lambda: float(self.c64.cpu.current_bus_cycle))

            # Configure metadata (sample_rate is filled in render_to_wav)
            sid_models = []
            for m in hdr.sidModels[:hdr.sidCount]:
                if m == '6581':
                    sid_models.append(0)
                elif m == '8580':
                    sid_models.append(1)
                else:
                    sid_models.append(-1)

            self._sidpro_export.set_metadata_config(
                clock_hz=int(hdr.clockFreq),
                standard='NTSC' if hdr.isNtsc else 'PAL',
                sid_count=int(hdr.sidCount),
                sid_models=sid_models,
                sid_bases=[int(x) for x in hdr.sidAddresses[:hdr.sidCount]],
                sample_rate=0,
                frame_rate=(60.0 if hdr.isNtsc else 50.0) / float(self._sidpro_telemetry_div),
                song=selected_song,
                title=str(hdr.title),
                author=str(hdr.author),
                released=str(hdr.released),
            )

            # RAM initial snapshot (post-load, post-reset, pre-init)
            self._sidpro_export.set_ram_snapshots(
                ram_initial=bytes(self.c64.memory.ram),
                ram_final=b""  # filled at end
            )

        # Set song number in A
        self.c64.cpu.a = (selected_song - 1) & 0xFF

        # Call init
        if hdr.initAddress != 0:
            SystemLogger.log('Playback', f"Calling init at ${hdr.initAddress:04X} (song {selected_song})", 'info')
            self.c64.call(hdr.initAddress, a=(selected_song - 1) & 0xFF, x=0, y=0)
        else:
            SystemLogger.log('Playback', 'No init address; skipping init', 'warn')

    def render_to_wav(self, out_path: str, seconds: float = 10.0, sample_rate: int = 44100,
                      progress_callback: Optional[Callable[[float], None]] = None) -> PlaybackResult:
        if self.header is None or self.sid_data is None:
            raise RuntimeError('No SID loaded')

        duration = float(seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Render duration must be a finite positive number of seconds')
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 96000:
            raise ValueError(f"Sample rate {sample_rate} must be an integer in [8000-96000]")

        hdr = self.header
        frames = int(round(duration * sample_rate))
        if frames < 1:
            raise ValueError('Render duration is shorter than one output sample')

        # Determine play cadence
        # Check if CIA timer based (speed bit pattern) or VBI
        use_cia_timing = False
        cia_frequency = 60.0  # Default to 60Hz if CIA-based

        if hdr.playAddress != 0:
            # Check speed bits - bit N set means song N uses CIA timer
            # For simplicity, use CIA timing if any speed bit is set
            if hdr.speed != 0:
                use_cia_timing = True
                # Estimate frequency from timer (rough approximation)
                cia_frequency = 50.0 if not hdr.isNtsc else 60.0

        cycles_per_frame = self.c64.model.cyclesPerFrame

        # SID-PRO: update sample_rate in metadata now that we know it
        if self._sidpro_export:
            cfg = self._sidpro_export.metadata.get('config') or {}
            cfg['sample_rate'] = int(sample_rate)
            self._sidpro_export.metadata['config'] = cfg

        if use_cia_timing:
            # CIA-based: call play routine at CIA frequency
            cycles_per_play = int(hdr.clockFreq / cia_frequency)
        else:
            # VBI-based: call play routine once per frame
            cycles_per_play = cycles_per_frame

        cycles_per_sample = hdr.clockFreq / float(sample_rate)

        # Simple fractional accumulator for CPU cycles per output sample
        cpu_acc = 0.0

        outp = Path(out_path)
        outp.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(outp), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)

            play_cycle_acc = 0
            frames_rendered = 0

            # SID-PRO telemetry scheduling
            telemetry_div = max(1, int(self._sidpro_telemetry_div))
            telemetry_period = int(cycles_per_frame) * telemetry_div
            next_telemetry_cycle = int(self.c64.cpu.cycles)
            telemetry_frame = 0
            pcm_buffer = array('h')
            progress_interval = max(1, sample_rate // 10)

            def capture_telemetry() -> None:
                nonlocal telemetry_frame
                if not self._sidpro_export:
                    return
                chips = [sid.snapshot_forensic(verbose=self._sidpro_verbose_sid) for sid in self.c64.sids]
                self._sidpro_export.add_telemetry_frame({
                    'frame': int(telemetry_frame),
                    'cycle': float(self.c64.cpu.cycles),
                    'chips': chips,
                })
                telemetry_frame += 1

            def flush_pcm() -> None:
                if not pcm_buffer:
                    return
                if sys.byteorder != 'little':
                    pcm_buffer.byteswap()
                wf.writeframesraw(pcm_buffer.tobytes())
                # ``array.clear`` is not available on every supported Python
                # runtime. Slice deletion clears in place while retaining the
                # reusable buffer allocation.
                del pcm_buffer[:]

            for n in range(frames):
                # Progress callback
                if progress_callback and n % progress_interval == 0:
                    progress = n / frames
                    progress_callback(progress)

                # advance emulation to match audio time
                cpu_acc += cycles_per_sample
                cyc = int(cpu_acc)
                if cyc > 0:
                    cpu_acc -= cyc
                    self.c64.step(cyc)
                    play_cycle_acc += cyc

                # Telemetry capture (may need to catch up multiple frames)
                if self._sidpro_export:
                    while int(self.c64.cpu.cycles) >= next_telemetry_cycle:
                        capture_telemetry()
                        next_telemetry_cycle += telemetry_period

                # Play call when we cross the play boundary
                if hdr.playAddress != 0 and play_cycle_acc >= cycles_per_play:
                    # Can cross multiple play calls if sample rate low vs cpu; loop
                    while play_cycle_acc >= cycles_per_play:
                        play_cycle_acc -= cycles_per_play
                        self.c64.call(hdr.playAddress, a=0, x=0, y=0)
                        frames_rendered += 1

                    if self._sidpro_export:
                        while int(self.c64.cpu.cycles) >= next_telemetry_cycle:
                            capture_telemetry()
                            next_telemetry_cycle += telemetry_period

                # Render audio sample - mix all SIDs
                s = 0.0
                if self.c64.sids:
                    for sid in self.c64.sids:
                        s += sid.render_sample()
                    s /= len(self.c64.sids)  # Average multiple SIDs

                pcm_buffer.append(_i16(s))
                if len(pcm_buffer) >= 4096:
                    flush_pcm()

            flush_pcm()
            if progress_callback:
                progress_callback(1.0)

        # SID-PRO finalize
        if self._sidpro_export and self._sidpro_recorder and self._sidpro_path:
            self._sidpro_recorder.assert_consistent()

            # Pack cycles as float64 little-endian
            a = array('d', (float(v) for v in self._sidpro_recorder.cycles))
            if sys.byteorder != 'little':
                a.byteswap()
            cycles_raw = a.tobytes()
            events_raw = bytes(self._sidpro_recorder.events)

            # Fill RAM final snapshot
            self._sidpro_export.set_bus_stream(cycles_f64=cycles_raw, events_u8=events_raw)
            if self._iopro_recorder and self._sidpro_io_trace:
                self._iopro_recorder.assert_consistent()
                io_a = array('d', (float(v) for v in self._iopro_recorder.cycles))
                if sys.byteorder != 'little':
                    io_a.byteswap()
                io_cycles_raw = io_a.tobytes()
                io_events_raw = bytes(self._iopro_recorder.events)
                self._sidpro_export.set_io_stream(cycles_f64=io_cycles_raw, events_u8=io_events_raw)
            # Replace the earlier ram_final placeholder
            self._sidpro_export.set_ram_snapshots(
                ram_initial=self._sidpro_export._ram_initial_raw,
                ram_final=bytes(self.c64.memory.ram),
            )

            self._sidpro_export.export_to_file(self._sidpro_path, compress=self._sidpro_compress)
            # Detach recorders
            try:
                self.c64.memory.uninstall_sidpro()
            except Exception:
                pass
            try:
                self.c64.memory.uninstall_iopro()
            except Exception:
                pass
            SystemLogger.log('Playback', f"SID-PRO forensic export written: {self._sidpro_path}", 'info')

        return PlaybackResult(str(outp), frames_rendered, frames)
