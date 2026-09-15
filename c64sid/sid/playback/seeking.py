"""Seeking support for SID-PRO exports - jump to arbitrary timestamps."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    from .c64_system import C64System
    from .sidpro_forensic import SIDProForensicExport


class SeekEngine:
    """Restore C64 system state from telemetry frames for seeking."""

    @staticmethod
    def find_nearest_frame(export: 'SIDProForensicExport', target_cycle: float) -> Optional[int]:
        """Find telemetry frame closest to target cycle."""
        frames = export.telemetry.get('frames', [])
        if not frames:
            return None

        # A later frame cannot be rewound to the requested position. Choose the
        # newest checkpoint at or before the target instead of the nearest one.
        best_idx = None
        for idx, frame in enumerate(frames):
            if frame.get('cycle', 0) > target_cycle:
                break
            best_idx = idx
        return best_idx

    @staticmethod
    def restore_sid_state(sid_chip, voice_data: Dict[str, Any]):
        """Restore SID voice state from telemetry."""
        osc = voice_data.get('osc', {})
        env = voice_data.get('env', {})
        regs = voice_data.get('reg', {})

        # Phase accumulator
        if 'acc' in osc:
            voice_idx = 0  # Need to know which voice
            # This would be called per voice
            # sid_chip.phase[voice_idx] = osc['acc']

        # Noise LFSR
        if 'lfsr' in osc:
            # sid_chip.noise[voice_idx] = osc['lfsr']
            pass

        # Envelope
        if 'out' in env:
            # sid_chip.env[voice_idx] = env['out']
            pass
        if 'state' in env:
            # sid_chip.env_state[voice_idx] = env['state']
            pass
        if 'counter' in env:
            # sid_chip.env_pipeline[voice_idx] = env['counter']
            pass
        if 'rate_counter' in env:
            # sid_chip.env_timer[voice_idx] = env.get('rate_counter', 0)
            pass

    @staticmethod
    def restore_filter_state(sid_chip, filter_data: Dict[str, Any]):
        """Restore SID filter state from telemetry."""
        if 'hp_int' in filter_data:
            sid_chip.filter_hp = float(filter_data['hp_int'])
        if 'bp_int' in filter_data:
            sid_chip.filter_bp = float(filter_data['bp_int'])
        if 'lp_int' in filter_data:
            sid_chip.filter_lp = float(filter_data['lp_int'])

    @staticmethod
    def restore_chip_state(sid_chip, chip_data: Dict[str, Any]):
        """Restore complete SID chip state."""
        # Registers
        registers = chip_data.get('registers', [])
        if registers:
            for i, val in enumerate(registers[:0x20]):
                sid_chip.regs[i] = val

        # Voices
        voices = chip_data.get('voices', [])
        for voice_idx, voice_data in enumerate(voices[:3]):
            osc = voice_data.get('osc', {})
            env = voice_data.get('env', {})

            # Phase accumulator
            if 'acc' in osc:
                sid_chip.phase[voice_idx] = int(osc['acc']) & 0xFFFFFF

            # Noise LFSR
            if 'lfsr' in osc:
                sid_chip.noise[voice_idx] = int(osc['lfsr']) & 0x7FFFFF

            # Envelope
            if 'out' in env:
                sid_chip.env[voice_idx] = int(env['out']) & 0xFF

            state_map = {'A': 'A', 'D': 'D', 'S': 'S', 'R': 'R'}
            if 'state' in env and env['state'] in state_map:
                sid_chip.env_state[voice_idx] = state_map[env['state']]

            if 'counter' in env:
                sid_chip.env_pipeline[voice_idx] = int(env['counter']) & 0xFF

            if 'rate_counter' in env:
                sid_chip.env_timer[voice_idx] = int(env['rate_counter'])

            # Gate state
            derived = voice_data.get('derived', {})
            if 'gate' in derived:
                sid_chip.gate[voice_idx] = bool(derived['gate'])

        # Filter
        filter_data = chip_data.get('filter', {})
        SeekEngine.restore_filter_state(sid_chip, filter_data)

    @staticmethod
    def restore_ram_state(system: 'C64System', ram_data: bytes):
        """Restore RAM from snapshot."""
        if len(ram_data) == 65536:
            system.memory.ram[:] = ram_data

    @staticmethod
    def seek_to_frame(system: 'C64System',
                      export: 'SIDProForensicExport',
                      frame_idx: int) -> bool:
        """Restore system state to specific telemetry frame.

        Returns:
            True if successful
        """
        frames = export.telemetry.get('frames', [])
        if frame_idx < 0 or frame_idx >= len(frames):
            return False

        frame = frames[frame_idx]

        # Restore CPU cycle counter
        if 'cycle' in frame:
            system.cpu.cycles = int(frame['cycle'])
            system.bus._cycle = int(frame['cycle'])

        # Restore SID chips
        chips_data = frame.get('chips', [])
        for chip_idx, chip_data in enumerate(chips_data):
            if chip_idx < len(system.sids):
                SeekEngine.restore_chip_state(system.sids[chip_idx], chip_data)

        # A frame can include an optional RAM checkpoint. Older exports only
        # have initial/final snapshots, which must not be mistaken for a frame
        # checkpoint.
        ram_checkpoint = frame.get('ram_checkpoint')
        if isinstance(ram_checkpoint, (bytes, bytearray)):
            SeekEngine.restore_ram_state(system, bytes(ram_checkpoint))

        return True

    @staticmethod
    def seek_to_cycle(system: 'C64System',
                      export: 'SIDProForensicExport',
                      target_cycle: float) -> bool:
        """Seek to specific CPU cycle using nearest telemetry frame."""
        frame_idx = SeekEngine.find_nearest_frame(export, target_cycle)
        if frame_idx is None:
            return False

        if not SeekEngine.seek_to_frame(system, export, frame_idx):
            return False

        # Step remaining cycles if needed
        frame = export.telemetry['frames'][frame_idx]
        current_cycle = frame.get('cycle', 0)

        if current_cycle < target_cycle:
            delta = int(target_cycle - current_cycle)
            if delta > 0:
                system.step(delta)

        return True

    @staticmethod
    def seek_to_time(system: 'C64System',
                     export: 'SIDProForensicExport',
                     target_seconds: float) -> bool:
        """Seek to specific time in seconds."""
        config = export.metadata.get('config', {})
        clock_hz = config.get('clock_hz', 985248)

        target_cycle = target_seconds * clock_hz
        return SeekEngine.seek_to_cycle(system, export, target_cycle)


class SeekablePlayer:
    """Player with seeking support."""

    def __init__(self, system: 'C64System', export: 'SIDProForensicExport'):
        self.system = system
        self.export = export
        self.current_frame = 0

    def seek(self, seconds: float) -> bool:
        """Seek to time in seconds."""
        return SeekEngine.seek_to_time(self.system, self.export, seconds)

    def get_duration(self) -> float:
        """Get total duration from telemetry."""
        frames = self.export.telemetry.get('frames', [])
        if not frames:
            return 0.0

        config = self.export.metadata.get('config', {})
        clock_hz = config.get('clock_hz', 985248)

        last_cycle = frames[-1].get('cycle', 0)
        return last_cycle / clock_hz

    def get_position(self) -> float:
        """Get current playback position in seconds."""
        config = self.export.metadata.get('config', {})
        clock_hz = config.get('clock_hz', 985248)
        return self.system.cpu.cycles / clock_hz
