import json
from pathlib import Path
import tempfile
import io
import unittest
from unittest.mock import patch

from capture.receiver import Receiver
from parser.framer import FramingError, PacketFramer
from storage.session_log import SessionLog
from tools.replay_capture import replay
from tools.replay_capture import main as replay_main


class SessionTests(unittest.TestCase):
    def test_export_preserves_bytes_live_recording_inputs_and_failed_destination(self):
        log = SessionLog(self.folder.name, {0x90: 4}, record_payload=True)
        try:
            log.write('diagnostic', message='観測')
            destination = Path(self.folder.name) / 'export.jsonl'
            log.export(destination)
            previous = destination.read_bytes()
            self.assertEqual(previous, log.path.read_bytes())
            log.write('diagnostic', message='continued')
            log.export(log.path)  # Existing same-source export remains a no-op.
            self.assertNotEqual(log.path.read_bytes(), previous)
            definitions = log.directory / 'PacketLength.used.txt'
            definition_bytes = definitions.read_bytes()
            with self.assertRaises(ValueError):
                log.export(definitions)
            self.assertEqual(definitions.read_bytes(), definition_bytes)
            with self.assertRaises(ValueError):
                log.export(destination, [destination])
            with patch('storage.observation_export.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    log.export(destination)
            with patch('storage.session_log.MAX_EXPORT_BYTES', 1), \
                    patch('storage.observation_export.MAX_EXPORT_BYTES', 1):
                with self.assertRaises(ValueError):
                    log.export(destination)
            self.assertEqual(destination.read_bytes(), previous)
            self.assertFalse(list(Path(self.folder.name).glob('*.tmp')))
            log.write('diagnostic', message='still recording')
            self.assertFalse(log.error)
        finally:
            log.close()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    def test_metadata_default_omits_payload_and_snapshots_definitions(self):
        log = SessionLog(self.folder.name, {0x90: 4})
        log.write('stream_chunk', data=b'secret', endpoints=['server'], stream_offset=0)
        log.close()
        text = log.path.read_text(encoding='utf-8')
        self.assertNotIn('data_hex', text)
        self.assertNotIn('secret', text)
        self.assertEqual((log.directory / 'PacketLength.used.txt').read_text(encoding='utf-8'), '0090 4\n')
        self.assertEqual(json.loads(text.splitlines()[1])['byte_count'], 6)
        with self.assertRaisesRegex(ValueError, 'Record receive bytes'):
            replay(log.path, {0x90: 4})

    def test_known_packets_before_unknown_survive_and_context_is_saved(self):
        log = SessionLog(self.folder.name, {0x90: 4}, record_payload=True)
        events, status = [], []
        receiver = Receiver('', None, {0x90: 4}, events.append, status.append, recorder=log)
        key = ('server', 5121, 'client', 50000)
        receiver._consume(key, 100, 0x12, b'', 1)
        receiver._consume(key, 101, 0x10, b'\x90\x00ab\x3c\x0c\x01\x02\x03\x04', 2)
        # Live parsing is stopped, but transport recording continues.
        receiver._consume(key, 111, 0x10, b'\x90\x00cd', 3)
        log.close()
        self.assertEqual([e.raw for e in events], [b'\x90\x00ab'])
        self.assertIn('previous=0x0090 length=4', status[-1])
        rows = [json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
        failure = next(row for row in rows if row['kind'] == 'framing_error')
        self.assertEqual(failure['stream_offset'], 4)
        self.assertEqual(failure['next_packet_id'], 0xc3c)
        self.assertEqual(failure['previous_packets'][-1]['applied_length'], 4)
        self.assertEqual(failure['boundary'], 'SYN')
        old = replay(log.path, {0x90: 4})
        new = replay(log.path, {0x90: 4, 0xc3c: 6})
        self.assertEqual(old['failed_connections'], 1)
        self.assertEqual(old['packet_counts'], {'0x0090': 1})
        self.assertEqual(new['failed_connections'], 0)
        self.assertEqual(new['packet_counts'], {'0x0090': 2, '0x0C3C': 1})
        self.assertTrue(new['session_end_present'])

    def test_framer_reports_previous_length_and_emits_completed_only_once(self):
        framer = PacketFramer({0x90: 4})
        with self.assertRaises(FramingError) as failure:
            framer.feed(b'\x90\x00ab\xff\xff')
        self.assertEqual(failure.exception.completed_packets, [(0x90, b'\x90\x00ab')])
        self.assertEqual(framer.snapshot()['previous_packets'][0]['offset'], 0)
        self.assertEqual(framer.offset, 4)
        with self.assertRaises(FramingError) as repeated:
            framer.feed(b'\x90\x00cd')
        self.assertEqual(repeated.exception.completed_packets, [])

    def test_log_size_limit_and_disk_failure_do_not_raise_into_capture(self):
        log = SessionLog(self.folder.name, {0x90: 4}, max_bytes=1)
        self.assertIn('size limit', log.error)
        log.write('ignored')
        log.close()
        log = SessionLog(self.folder.name, {0x90: 4})
        with patch.object(log.file, 'write', side_effect=OSError('disk full')):
            log.write('test')
            self.assertIn('disk full', log.error)
        log.close()

    def test_missing_recorded_bytes_are_not_silently_replayed(self):
        log = SessionLog(self.folder.name, {0x90: 4}, record_payload=True)
        log.write('stream_chunk', endpoints=['server', 1, 'client', 2], initial_sequence=100,
                  stream_offset=4, data=b'\x90\x00ab')
        log.close()
        with self.assertRaisesRegex(ValueError, 'Missing or reordered'):
            replay(log.path, {0x90: 4})

    def test_tcp_gap_is_reported_as_incomplete_even_with_empty_framer_buffer(self):
        log = SessionLog(self.folder.name, {0x90: 4}, record_payload=True)
        receiver = Receiver('', None, {0x90: 4}, lambda event: None, lambda message: None, recorder=log)
        key = ('server', 5121, 'client', 50000)
        receiver._consume(key, 100, 0x12, b'', 1)
        receiver._consume(key, 103, 0x10, b'ab', 2)
        log.close()
        report = replay(log.path, {0x90: 4})
        self.assertEqual(report['incomplete_streams'][0]['buffered_bytes'], 0)
        self.assertEqual(report['incomplete_streams'][0]['tcp_pending_segments'], 1)

    def test_replay_command_writes_a_report(self):
        log = SessionLog(self.folder.name, {0x90: 4}, record_payload=True)
        receiver = Receiver('', None, {0x90: 4}, lambda event: None, lambda message: None, recorder=log)
        key = ('server', 5121, 'client', 50000)
        receiver._consume(key, 100, 0x12, b'', 1)
        receiver._consume(key, 101, 0x10, b'\x90\x00ab', 2)
        log.close()
        output = Path(self.folder.name) / 'replay.json'
        with patch('sys.argv', ['replay_capture', str(log.path), '--definitions',
                               str(log.directory / 'PacketLength.used.txt'), '--output', str(output)]), \
             patch('sys.stdout', new=io.StringIO()):
            replay_main()
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['packet_counts'], {'0x0090': 1})
        self.assertEqual(report['failed_connections'], 0)
