import json
import struct
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from reconstruction.emulator_profiles import set_target, target
from storage.session_log import SessionLog
from tests.support.dialogue import packet
from tools.cli_emulator import active_emulator, add_emulator_argument, apply_emulator


def _dialogue_log(folder, definitions):
    log = SessionLog(folder, definitions, record_payload=True)
    log.write('capture_format', transport='tcp_segments', capture_send=True)
    incoming, outgoing = ('server', 1, 'client', 2), ('client', 2, 'server', 1)
    payload = (packet(0xb4, struct.pack('<I', 42) + b'hello\0').raw
               + packet(0xb6, struct.pack('<I', 42)).raw)
    for endpoints, seq, flags, data, time, direction in (
            (outgoing, 10, 2, b'', 0, 'SEND'),
            (incoming, 30, 18, b'', 0, 'RECV'),
            (incoming, 31, 16, payload, 1, 'RECV')):
        log.write('tcp_segment', endpoints=endpoints, sequence=seq, flags=flags, data=data,
                  timestamp=time, direction=direction)
    log.close()
    return log


class CliEmulatorHelperTests(unittest.TestCase):
    def tearDown(self):
        set_target('auriga')

    def test_apply_emulator_rejects_unknown_and_switches_active_target(self):
        self.assertEqual(apply_emulator('auriga'), 'auriga')
        self.assertEqual(active_emulator(), 'auriga')
        self.assertEqual(apply_emulator('rathena'), 'rathena')
        self.assertEqual(target(), 'rathena')
        with self.assertRaises(ValueError):
            apply_emulator('hercules')

    def test_argument_defaults_to_auriga_and_accepts_choices(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_emulator_argument(parser)
        self.assertEqual(parser.parse_args([]).emulator, 'auriga')
        self.assertEqual(parser.parse_args(['--emulator', 'rathena']).emulator, 'rathena')
        with self.assertRaises(SystemExit):
            with patch('sys.stderr', StringIO()):
                parser.parse_args(['--emulator', 'hercules'])


class CliEmulatorSessionTests(unittest.TestCase):
    def tearDown(self):
        set_target('auriga')

    def test_analyze_session_cli_selects_rathena_generation_profiles(self):
        from tools.analyze_session import main

        definitions = {0xb4: -1, 0xb6: 6}
        with tempfile.TemporaryDirectory() as folder:
            log = _dialogue_log(folder, definitions)
            definitions_path = log.directory / 'PacketLength.used.txt'
            output = log.directory / 'session.json'
            argv = ['analyze_session', str(log.path), '--definitions', str(definitions_path),
                    '--output', str(output), '--emulator', 'rathena']
            with patch('sys.argv', argv), patch('sys.stdout', StringIO()) as stdout:
                main()
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['emulator'], 'rathena')
            dialogue_path = report['dialogue_profile']['path'].replace('\\', '/')
            status_path = report['status_id_map']['path'].replace('\\', '/')
            self.assertIn('/config/rathena/dialogue.json', dialogue_path)
            self.assertIn('/config/rathena/status_ids.json', status_path)
            self.assertIn('Emulator rathena', stdout.getvalue())
            self.assertEqual(target(), 'rathena')

    def test_analyze_dialogues_cli_default_stays_auriga(self):
        from tools.analyze_dialogues import main

        definitions = {0xb4: -1, 0xb6: 6}
        with tempfile.TemporaryDirectory() as folder:
            log = _dialogue_log(folder, definitions)
            definitions_path = log.directory / 'PacketLength.used.txt'
            output = log.directory / 'dialogues.json'
            argv = ['analyze_dialogues', str(log.path), '--definitions', str(definitions_path),
                    '--output', str(output)]
            with patch('sys.argv', argv), patch('sys.stdout', StringIO()) as stdout:
                main()
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['emulator'], 'auriga')
            self.assertIn('Emulator auriga', stdout.getvalue())
            self.assertEqual(target(), 'auriga')
