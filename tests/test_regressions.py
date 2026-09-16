from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from c64sid.sid.c64_system import C64System
from c64sid.sid.playback.seeking import SeekEngine
from c64sid.sid.sid_parser import parse_sid_header
from c64sid.sid.sidpro_binary import export_to_binary, load_from_binary
from c64sid.sid.sidpro_forensic import SIDProForensicExport
from tools.sidpro_to_csv import export_bus_events_csv
from tools.sidpro_to_vgm import write_vgm


class RegressionTests(unittest.TestCase):
    def test_package_versions_are_aligned(self) -> None:
        import c64sid
        import patches

        self.assertEqual(c64sid.__version__, '0.1.0')
        self.assertEqual(patches.__version__, c64sid.__version__)

    def test_peripheral_interrupts_queue_with_correct_line_type(self) -> None:
        system = C64System()
        system.memory.cia1.irqLine = True
        system._poll_irqs()
        system.memory.cia2.irqLine = True
        system._poll_irqs()
        self.assertEqual([event.type for event in system._pending_irqs], ['IRQ', 'NMI'])

    def test_call_stops_at_routine_return(self) -> None:
        system = C64System()
        system.cpu.pc = 0x2000
        system.memory.ram[0x1000] = 0x60  # RTS
        elapsed = system.call(0x1000, max_cycles=32)
        self.assertLess(elapsed, 32)
        self.assertEqual(system.cpu.pc, 0x2000)

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

    def test_csv_supports_uncompressed_exports_and_vgm_is_rejected(self) -> None:
        export = SIDProForensicExport()
        export.set_bus_stream(cycles_f64=b'\x00' * 8, events_u8=bytes([0, 1, 2]))
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / 'events.csv'
            export_bus_events_csv(export, str(csv_path))
            self.assertIn('Register_Hex', csv_path.read_text(encoding='utf-8'))
            with self.assertRaises(ValueError):
                write_vgm(export, str(Path(directory) / 'events.vgm'))

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


if __name__ == '__main__':
    unittest.main()
