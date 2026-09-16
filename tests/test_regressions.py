from __future__ import annotations

import tempfile
import unittest
import zlib
from pathlib import Path

from c64sid.sid.c64_system import C64System
from c64sid.sid.playback.seeking import SeekEngine
from c64sid.sid.sid_parser import parse_sid_header
from c64sid.sid.sidpro_binary import CHUNK_EOF, MAGIC, export_to_binary, load_from_binary
from c64sid.sid.sidpro_forensic import SIDProForensicExport
from tools.sidpro_to_csv import export_analysis_csv, export_bus_events_csv


class RegressionTests(unittest.TestCase):
    def test_package_versions_are_aligned(self) -> None:
        import c64sid

        self.assertEqual(c64sid.__version__, '0.3.2')

    @staticmethod
    def _minimal_sid(*, songs: int = 1, start_song: int = 1) -> bytes:
        """Create a PSID whose init routine immediately returns."""
        raw = bytearray(0x77)
        raw[0:4] = b'PSID'
        raw[4:6] = (1).to_bytes(2, 'big')
        raw[6:8] = (0x76).to_bytes(2, 'big')
        raw[8:10] = (0x1000).to_bytes(2, 'big')
        raw[10:12] = (0x1000).to_bytes(2, 'big')
        raw[14:16] = songs.to_bytes(2, 'big')
        raw[16:18] = start_song.to_bytes(2, 'big')
        raw[0x76] = 0x60  # RTS
        return bytes(raw)

    def test_bundled_resid_combined_waveform_tables_load(self) -> None:
        from c64sid.sid.resid_lut import load_combined_waveform_table

        triangle_saw = load_combined_waveform_table('6581', 0x30)
        pulse_saw = load_combined_waveform_table('6581', 0x60)
        self.assertEqual(len(triangle_saw), 4096)
        self.assertNotEqual(triangle_saw, pulse_saw)
        self.assertEqual(len(load_combined_waveform_table('8580', 0x70)), 4096)

    def test_sid_chip_uses_bundled_combined_waveform_tables(self) -> None:
        from c64sid.sid.resid_lut import load_combined_waveform_table
        from c64sid.sid.sid_chip import SidChip

        table = load_combined_waveform_table('6581', 0x30)
        self.assertIsNotNone(table)
        index = next(index for index, value in enumerate(table) if value not in (0, 4095))
        chip = SidChip(985_248)
        chip.set_model('6581')
        chip.phase[0] = index << 12
        chip.env[0] = 255
        chip.regs[0x04] = 0x30
        chip.regs[0x18] = 0x0F
        self.assertAlmostEqual(chip.render_sample(), (((table[index] / 2047.5) - 1.0) / 3.0))

    def test_peripheral_interrupts_queue_with_correct_line_type(self) -> None:
        system = C64System()
        system.memory.cia1.irqLine = True
        system._poll_irqs()
        system.memory.cia2.irqLine = True
        system._poll_irqs()
        self.assertEqual([event.type for event in system._pending_irqs], ['IRQ', 'NMI'])

    def test_analysis_uses_gate_edges_and_stable_pattern_ids(self) -> None:
        from c64sid.sid.analysis.bpm_detector import BPMDetector
        from c64sid.sid.analysis.pattern_finder import PatternFinder

        export = SIDProForensicExport()
        export.metadata['config'] = {'clock_hz': 1_000}
        frames = []
        for onset in range(10):
            cycle = onset * 500
            frames.extend([
                {'frame': cycle, 'cycle': cycle, 'chips': [{'voices': [{'derived': {'gate': True}}]}]},
                {'frame': cycle + 100, 'cycle': cycle + 100, 'chips': [{'voices': [{'derived': {'gate': True}}]}]},
                {'frame': cycle + 200, 'cycle': cycle + 200, 'chips': [{'voices': [{'derived': {'gate': False}}]}]},
            ])
        export.telemetry['frames'] = frames
        self.assertEqual(BPMDetector.detect(export)['bpm'], 120.0)

        loops_first = PatternFinder.find_loops(export, min_length=2)
        loops_second = PatternFinder.find_loops(export, min_length=2)
        self.assertEqual(loops_first, loops_second)
        self.assertTrue(all(len(loop['pattern_hash']) == 64 for loop in loops_first))

    def test_call_stops_at_routine_return(self) -> None:
        system = C64System()
        system.cpu.pc = 0x2000
        system.memory.ram[0x1000] = 0x60  # RTS
        elapsed = system.call(0x1000, max_cycles=32)
        self.assertLess(elapsed, 32)
        self.assertEqual(system.cpu.pc, 0x2000)

    def test_playback_selects_subsongs_validates_arguments_and_reports_completion(self) -> None:
        import math
        import wave
        from c64sid.sid.playback import PlaybackCoordinator

        player = PlaybackCoordinator()
        player.load_sid_bytes(self._minimal_sid(songs=2, start_song=2), song=1)
        self.assertEqual(player.song, 1)
        with self.assertRaises(ValueError):
            player.load_sid_bytes(self._minimal_sid(songs=2), song=3)
        with self.assertRaises(ValueError):
            player.enable_sidpro_export('capture.sidpro', telemetry_rate=0)

        progress = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'nested' / 'tone.wav'
            result = player.render_to_wav(output, seconds=0.01, sample_rate=8_000, progress_callback=progress.append)
            self.assertEqual(result.samples, 80)
            self.assertEqual(progress[0], 0.0)
            self.assertEqual(progress[-1], 1.0)
            with wave.open(str(output), 'rb') as wav:
                self.assertEqual(wav.getnframes(), 80)

        with self.assertRaises(ValueError):
            player.render_to_wav('ignored.wav', seconds=0, sample_rate=8_000)
        with self.assertRaises(ValueError):
            player.render_to_wav('ignored.wav', seconds=math.nan, sample_rate=8_000)

    def test_parser_rejects_bad_offsets_and_sid_addresses(self) -> None:
        raw = bytearray(0x7D)
        raw[0:4] = b'PSID'
        raw[4:6] = (3).to_bytes(2, 'big')
        raw[6:8] = (0x7C).to_bytes(2, 'big')
        raw[8:10] = (0x1000).to_bytes(2, 'big')
        raw[10:12] = (0x1000).to_bytes(2, 'big')
        raw[14:16] = (1).to_bytes(2, 'big')
        raw[16:18] = (1).to_bytes(2, 'big')
        raw[0x7A] = 0x80
        header, _ = parse_sid_header(bytes(raw))
        self.assertEqual(header.sidAddresses, [0xD400])
        raw[6:8] = (0xFFFF).to_bytes(2, 'big')
        with self.assertRaises(ValueError):
            parse_sid_header(bytes(raw))

    def test_inspector_formats_parseable_sid_metadata(self) -> None:
        from tools.inspect_sid import format_header, header_to_dict

        header, payload = parse_sid_header(self._minimal_sid(songs=2, start_song=2))
        metadata = header_to_dict(header, len(payload))
        self.assertEqual(metadata['songs'], 2)
        self.assertEqual(metadata['start_song'], 2)
        self.assertEqual(metadata['sid_chips'], [{'address': '$D400', 'model': 'UNKNOWN'}])
        self.assertIn('Songs: 2 (default: 2)', format_header(metadata))

    def test_binary_export_preserves_all_supported_streams(self) -> None:
        export = SIDProForensicExport()
        export.set_metadata_config(title='Test', author='', released='', clock_hz=985248,
                                   standard='PAL', sid_count=1, sid_models=['6581'],
                                   sid_bases=[0xD400], sample_rate=44100, frame_rate=50,
                                   song=1)
        export.set_bus_stream(cycles_f64=b'\x00' * 8, events_u8=bytes([0, 1, 2]))
        export.set_ram_snapshots(ram_initial=b'\x00' * 65536, ram_final=b'\x01' * 65536)
        export.telemetry['frames'].append({'cycle': 0, 'chips': []})
        export.analysis = {'bpm': 120}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.sidprob'
            export_to_binary(export.export_to_dict(compress=False), str(path))
            loaded = load_from_binary(str(path))
            self.assertEqual(loaded['_bus_events_decoded'], [(0.0, 0, 1, 2)])
            self.assertEqual(loaded['binary']['ram_initial'], b'\x00' * 65536)
            self.assertEqual(loaded['binary']['ram_final'], b'\x01' * 65536)
            self.assertEqual(loaded['analysis'], {'bpm': 120})

            malformed = {
                'missing-eof.sidprob': MAGIC,
                'truncated-header.sidprob': MAGIC + b'\x01\x00\x00',
                'eof-with-payload.sidprob': (
                    MAGIC + bytes([CHUNK_EOF, 0]) + (1).to_bytes(4, 'little')
                    + (0).to_bytes(4, 'little') + b'x'
                ),
            }
            for filename, raw in malformed.items():
                malformed_path = Path(directory) / filename
                malformed_path.write_bytes(raw)
                with self.assertRaises(ValueError, msg=filename):
                    load_from_binary(str(malformed_path))

            # A valid outer chunk with an incomplete event must report a
            # validation error, rather than leaking an IndexError.
            malformed_path = Path(directory) / 'truncated-event.sidprob'
            malformed_path.write_bytes(
                MAGIC
                + bytes([2, 0])
                + (2).to_bytes(4, 'little')
                + zlib.crc32(b'\x01\x00').to_bytes(4, 'little')
                + b'\x01\x00'
                + bytes([CHUNK_EOF, 0])
                + (0).to_bytes(4, 'little')
                + (0).to_bytes(4, 'little')
            )
            with self.assertRaises(ValueError):
                load_from_binary(str(malformed_path))

    def test_seeking_restores_ram_and_does_not_seek_past_target(self) -> None:
        system = C64System()
        SeekEngine.restore_ram_state(system, bytes([7]) * 65536)
        self.assertEqual(system.memory.ram[0], 7)
        export = SIDProForensicExport()
        export.telemetry['frames'] = [{'cycle': 10}, {'cycle': 20}]
        self.assertEqual(SeekEngine.find_nearest_frame(export, 15), 0)

    def test_seeking_restores_voice_state(self) -> None:
        from c64sid.sid.sid_chip import SidChip
        from c64sid.sid.sid_types import C64Config

        sid = SidChip(985248, C64Config())
        SeekEngine.restore_sid_state(sid, {
            'osc': {'acc': 0x123456, 'lfsr': 0x12345},
            'env': {'out': 77, 'state': 'D', 'counter': 12, 'rate_counter': 34},
            'reg': {'freq': 0x3456, 'pw': 0x789, 'ctrl': 0x21, 'ad': 0x42, 'sr': 0xA3},
            'derived': {'gate': True},
        }, 1)
        self.assertEqual(sid.phase[1], 0x123456)
        self.assertEqual(sid.noise[1], 0x12345)
        self.assertEqual(sid.env[1], 77)
        self.assertEqual(sid.env_state[1], 'D')
        self.assertTrue(sid.gate[1])
        self.assertEqual(sid.regs[0x07:0x0E], bytes([0x56, 0x34, 0x89, 0x07, 0x21, 0x42, 0xA3]))

    def test_csv_supports_uncompressed_exports(self) -> None:
        export = SIDProForensicExport()
        export.set_bus_stream(cycles_f64=b'\x00' * 8, events_u8=bytes([0, 1, 2]))
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / 'events.csv'
            export_bus_events_csv(export, str(csv_path))
            self.assertIn('Register_Hex', csv_path.read_text(encoding='utf-8'))
            analysis_path = Path(directory) / 'analysis.csv'
            export_analysis_csv(export, str(analysis_path))
            self.assertIn('BPM', analysis_path.read_text(encoding='utf-8'))

    def test_direct_voice_mix_is_not_doubled(self) -> None:
        from c64sid.sid.sid_chip import SidChip
        from c64sid.sid.sid_types import C64Config

        sid = SidChip(985248, C64Config())
        sid.env[1] = 255
        sid.regs[0x0B] = 0x20  # voice 2 sawtooth
        sid.regs[0x08] = 0xFF
        sid.regs[0x18] = 0x0F
        sid.phase[1] = 0xFFFFFF
        # A single unfiltered voice is scaled exactly once by the final /3 mix.
        self.assertAlmostEqual(sid.render_sample(), 1.0 / 3.0, places=4)

    def test_live_example_renders_pcm_wav(self) -> None:
        import wave
        from examples.render_live_tone import render_tone

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'live-tone.wav'
            frames = render_tone(output, seconds=0.01, sample_rate=8_000, frequency=440)
            self.assertEqual(frames, 80)
            with wave.open(str(output), 'rb') as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 8_000))
                self.assertEqual(wav.getnframes(), frames)


if __name__ == '__main__':
    unittest.main()
