import unittest
import struct
import tempfile

from capture.protocol_probe import InitialProtocolProbe
from capture.receiver import Receiver


class ProtocolProbeTests(unittest.TestCase):
    def test_verified_character_login_echo_is_consumed_once_at_syn_boundary_and_replays(self):
        from storage.session_log import SessionLog
        from tools.replay_capture import replay
        incoming = ('server', 6121, 'client', 50000)
        account = 4631724
        login = struct.pack('<HI', 0x65, account) + bytes(11)
        echo = struct.pack('<I', account)
        for pieces in ((echo + b'\x90\x00ab',), (echo[:1], echo[1:3], echo[3:], b'\x90\x00ab')):
            with self.subTest(pieces=len(pieces)), tempfile.TemporaryDirectory() as folder:
                events = []
                log = SessionLog(folder, {0x65: 17, 0x90: 4}, record_payload=True)
                r = Receiver('server', 6121, {0x65: 17, 0x90: 4}, events.append, lambda x:None,
                             capture_send=True, recorder=log)
                outgoing = r.reverse_key(incoming)
                r._consume(outgoing, 100, 2, b'', 0, direction='SEND')
                r._consume(incoming, 200, 18, b'', 0)
                r._consume(outgoing, 101, 16, login, 1, direction='SEND')
                seq = 201
                for data in pieces:
                    r._consume(incoming, seq, 16, data, 2)
                    seq += len(data)
                log.close()
                self.assertEqual([event.packet_id for event in events], [0x65, 0x90])
                self.assertEqual(r.stats['verified_account_echoes'], 1)
                self.assertEqual(r.stats['framing_errors'], 0)
                replayed = replay(log.path, r.definitions)
                self.assertEqual(replayed['failed_connections'], 0)
                self.assertEqual(replayed['packet_counts']['0x0090'], 1)
                # The special preamble rule never applies to a later unknown packet.
                r._consume(incoming, seq, 16, echo, 3)
                self.assertEqual(r.stats['framing_errors'], 1)
                r._consume(outgoing, 500, 2, b'', 4, direction='SEND')
                r._consume(incoming, 600, 18, b'', 4)
                r._consume(incoming, 601, 16, echo, 5)
                self.assertEqual(r.stats['framing_errors'], 2)
                self.assertEqual(r.stats['verified_account_echoes'], 1)
        probe = InitialProtocolProbe({0x90: 4}, expected_account=0x00100090)
        self.assertEqual(probe.feed(struct.pack('<I', 0x00100090) + b'\x90\x00ab'), ('GAME', b'\x90\x00ab'))
        for payload in (struct.pack('<I', account + 1), b'\xff\xff' + echo):
            with self.subTest(payload=payload):
                r = Receiver('server', 6121, {0x65: 17}, lambda e:None, lambda x:None, capture_send=True)
                outgoing = r.reverse_key(incoming)
                r._consume(outgoing, 100, 2, b'', 0, direction='SEND')
                r._consume(incoming, 200, 18, b'', 0)
                r._consume(outgoing, 101, 16, login, 1, direction='SEND')
                r._consume(incoming, 201, 16, payload, 2)
                self.assertEqual(r.stats['framing_errors'], 1)
                self.assertEqual(r.stats['verified_account_echoes'], 0)

    def test_fragmented_http_start_line(self):
        probe = InitialProtocolProbe({0x90: 4})
        for fragment in (b'P', b'OS', b'T /event HTTP/1.1\r'):
            self.assertEqual(probe.feed(fragment), ('PENDING', b''))
        self.assertEqual(probe.feed(b'\nContent-Length: 0\r\n\r\n'), ('HTTP', b''))
        self.assertEqual(probe.feed(b'any body'), ('HTTP', b''))

    def test_response_and_http2_preface(self):
        for wire in (b'HTTP/1.0 200 OK\r\n\r\n', b'GET / HTTP/1.1\r\n', InitialProtocolProbe.HTTP2_PREFACE):
            with self.subTest(wire=wire):
                self.assertEqual(InitialProtocolProbe({}).feed(wire), ('HTTP', b''))

    def test_defined_game_id_wins_and_payload_is_not_scanned(self):
        packet = b'POST / HTTP/1.1\r\n'
        self.assertEqual(InitialProtocolProbe({0x4f50: len(packet)}).feed(packet), ('GAME', packet))
        data = b'\xff\xff' + packet
        self.assertEqual(InitialProtocolProbe({}).feed(data), ('GAME', data))
        data = b'\x90\x00POST / HTTP/1.1\r\n'
        self.assertEqual(InitialProtocolProbe({0x90: len(data)}).feed(data), ('GAME', data))

    def test_invalid_or_overlong_start_is_forwarded_without_skipping(self):
        for wire in (b'POST / invalid\r\n', b'POX', b'POST ' + b'a' * 40):
            self.assertEqual(InitialProtocolProbe({}, max_start_line=32).feed(wire), ('GAME', wire))

    def test_ordinary_game_fragments_are_preserved(self):
        probe = InitialProtocolProbe({0x90: 4})
        self.assertEqual(probe.feed(b'\x90'), ('GAME', b'\x90'))
        self.assertEqual(probe.feed(b'\x00ab'), ('GAME', b'\x00ab'))

    def test_http_passes_both_directions_and_new_syn_reopens_game_parsing(self):
        events, statuses = [], []
        receiver = Receiver('server', 6900, {0x90: 4}, events.append, statuses.append, capture_send=True)
        incoming = ('server', 6900, 'client', 50000)
        outgoing = receiver.reverse_key(incoming)
        receiver._consume(outgoing, 100, 0x02, b'', 1, direction='SEND')
        receiver._consume(incoming, 200, 0x12, b'', 2)
        receiver._consume(outgoing, 101, 0x10, b'PO', 3, direction='SEND')
        receiver._consume(outgoing, 103, 0x10, b'ST / HTTP/1.1\r\n\r\n', 4, direction='SEND')
        receiver._consume(incoming, 201, 0x10, b'HTTP/1.1 200 OK\r\n\r\n', 5)
        self.assertFalse(events)
        self.assertEqual(receiver.stats['framing_errors'], 0)
        self.assertEqual(receiver.stats['passed_http_connections'], 1)
        self.assertIn('PASS HTTP', statuses[-1])
        self.assertFalse(receiver.connections)
        receiver._consume(outgoing, 500, 0x02, b'', 6, direction='SEND')
        receiver._consume(outgoing, 501, 0x10, b'\x90\x00ab', 7, direction='SEND')
        self.assertEqual([(e.direction, e.raw) for e in events], [('SEND', b'\x90\x00ab')])

    def test_unknown_game_and_headerless_echo_still_stop(self):
        statuses = []
        receiver = Receiver('', None, {0x90: 4}, lambda event: None, statuses.append)
        key = ('server', 6121, 'client', 50000)
        receiver._consume(key, 100, 0x12, b'', 1)
        receiver._consume(key, 101, 0x10, b'\xac\xac\x46\x00', 2)
        self.assertEqual(receiver.stats['framing_errors'], 1)
        self.assertEqual(receiver.stats['passed_http_connections'], 0)
        self.assertIn('0xACAC', statuses[-1])

    def test_deferred_peer_syn_ack_does_not_reopen_passed_http(self):
        receiver = Receiver('server', 6900, {0x90: 4}, lambda event: None, lambda message: None, capture_send=True)
        incoming = ('server', 6900, 'client', 50000)
        outgoing = receiver.reverse_key(incoming)
        receiver._consume(outgoing, 100, 0x02, b'', 1, direction='SEND')
        receiver._consume(outgoing, 101, 0x10, b'POST / HTTP/1.1\r\n', 3, direction='SEND')
        receiver._consume(incoming, 200, 0x12, b'', 2)
        receiver._consume(incoming, 201, 0x10, b'HTTP/1.1 200 OK\r\n', 4)
        self.assertEqual(receiver.stats['passed_http_connections'], 1)
        self.assertEqual(receiver.stats['framing_errors'], 0)
        self.assertFalse(receiver.connections)

