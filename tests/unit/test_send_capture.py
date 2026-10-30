import json
import tempfile
import unittest
from unittest.mock import patch
from scapy.all import Ether, IP, IPv6, TCP, Raw

from capture.process_monitor import Endpoint
from capture.receiver import Receiver
from storage.session_log import SessionLog
from tools.replay_capture import replay


class SendCaptureTests(unittest.TestCase):
    def setUp(self):
        self.events, self.status = [], []
        self.endpoint = Endpoint('10.0.0.2', 50000, '10.0.0.1', 6900, 42, 'ESTABLISHED')
        self.r = Receiver('', None, {0x90: 4}, self.events.append, self.status.append,
                          process_pid=42, capture_send=True)
        self.r.allowed.add(self.endpoint.key)

    def send(self, seq, payload=b'', flags='A', direction='SEND', receiver=None):
        key = self.r.reverse_key(self.endpoint.key) if direction == 'SEND' else self.endpoint.key
        packet = IP(src=key[0], dst=key[2]) / TCP(sport=key[1], dport=key[3], seq=seq, flags=flags)
        if payload:
            packet /= Raw(payload)
        (receiver or self.r)._handle(packet)

    def test_bidirectional_reassembly_with_identical_sequence_numbers(self):
        self.send(100, flags='S')
        self.send(100, flags='SA', direction='RECV')
        self.send(103, b'ab')
        self.send(101, b'\x90\x00cd', direction='RECV')
        self.send(101, b'\x90\x00')
        self.send(101, b'\x90\x00ab')  # Retransmission must not duplicate SEND.
        self.assertEqual([(e.direction, e.raw) for e in self.events],
                         [('RECV', b'\x90\x00cd'), ('SEND', b'\x90\x00ab')])
        self.assertTrue(all(e.source == 'NPCAP' for e in self.events))
        self.assertEqual(self.r.stats['recv_packets'], 1)
        self.assertEqual(self.r.stats['send_packets'], 1)

    def test_send_capture_is_opt_in(self):
        self.r.capture_send = False
        self.send(100, flags='S')
        self.send(101, b'\x90\x00ab')
        self.assertFalse(self.events)
        self.assertFalse(self.r.connections)

    def test_unknown_send_does_not_stop_receive_or_resynchronize(self):
        self.send(100, flags='S')
        self.send(100, flags='SA', direction='RECV')
        self.send(101, b'\xff\xff')
        self.send(103, b'\x90\x00ab')
        self.send(101, b'\x90\x00cd', direction='RECV')
        self.assertEqual([e.direction for e in self.events], ['RECV'])
        self.assertIn('SEND framing stopped', self.status[0])
        self.send(500, flags='S')
        self.send(501, b'\x90\x00ef')
        self.assertEqual([e.direction for e in self.events], ['RECV', 'SEND'])

    def test_both_directions_replayed_after_process_discovery(self):
        self.r.allowed.clear()
        self.send(100, flags='S')
        self.send(200, flags='SA', direction='RECV')
        self.send(101, b'\x90\x00ab')
        self.send(201, b'\x90\x00cd', direction='RECV')
        with patch('capture.receiver.discover', return_value={self.endpoint}):
            self.r.refresh_connections()
        self.assertEqual({(e.direction, e.raw) for e in self.events},
                         {('SEND', b'\x90\x00ab'), ('RECV', b'\x90\x00cd')})
        with patch('capture.receiver.discover', return_value=set()):
            self.r.refresh_connections()
        self.assertFalse(self.r.connections)
        self.assertFalse(self.r.stream_directions)

    def test_manual_filters_match_remote_endpoints_in_both_directions(self):
        receiver = Receiver('10.0.0.1', 6900, {0x90: 4}, self.events.append,
                            self.status.append, capture_send=True)
        self.send(100, flags='S', receiver=receiver)
        self.send(100, flags='SA', direction='RECV', receiver=receiver)
        self.send(101, b'\x90\x00ab', receiver=receiver)
        self.send(101, b'\x90\x00cd', direction='RECV', receiver=receiver)
        self.assertEqual([e.direction for e in self.events], ['SEND', 'RECV'])
        with patch('capture.receiver.get_working_ifaces', return_value=['adapter']), \
             patch('capture.receiver.AsyncSniffer') as factory:
            receiver.start()
            self.assertEqual(factory.call_args.kwargs['filter'], 'tcp and host 10.0.0.1 and port 6900')

    def test_ambiguous_manual_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Manual SEND capture requires'):
            Receiver('', None, {0x90: 4}, self.events.append, self.status.append, capture_send=True)

    def test_send_padding_is_not_application_data(self):
        self.r.definitions = {0: 2, 0x90: 4}
        base = (Ether(src='00:00:00:00:00:01', dst='00:00:00:00:00:02') /
                IP(src='10.0.0.2', dst='10.0.0.1') /
                TCP(sport=50000, dport=6900, seq=100, flags='S'))
        self.r._handle(Ether(bytes(base) + bytes(6)))
        self.assertFalse(self.events)
        self.send(101, b'\x90\x00ab')
        self.assertEqual([(e.direction, e.packet_id) for e in self.events], [('SEND', 0x90)])

    def test_ipv6_send_socket_ownership(self):
        self.r.allowed = {('2001:db8::1', 6900, '2001:db8::2', 50000)}
        base = IPv6(src='2001:db8::2', dst='2001:db8::1')
        self.r._handle(base / TCP(sport=50000, dport=6900, seq=100, flags='S'))
        self.r._handle(base / TCP(sport=50000, dport=6900, seq=101, flags='A') / Raw(b'\x90\x00ab'))
        self.assertEqual([e.direction for e in self.events], ['SEND'])

    def test_reset_closes_both_half_streams(self):
        self.send(100, flags='S')
        self.send(200, flags='SA', direction='RECV')
        self.assertEqual(len(self.r.connections), 2)
        self.send(101, flags='R')
        self.assertFalse(self.r.connections)

    def test_send_and_receive_log_replay_preserves_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            log = SessionLog(folder, {0x90: 4}, record_payload=True)
            receiver = Receiver('', None, {0x90: 4}, self.events.append, self.status.append,
                                process_pid=42, capture_send=True, recorder=log)
            receiver.allowed = {self.endpoint.key}
            self.send(100, flags='S', receiver=receiver)
            self.send(200, flags='SA', direction='RECV', receiver=receiver)
            self.send(101, b'\x90\x00ab', receiver=receiver)
            self.send(201, b'\x90\x00cd', direction='RECV', receiver=receiver)
            log.close()
            report = replay(log.path, {0x90: 4})
            self.assertEqual(report['packet_counts_by_direction'],
                             {'RECV': {'0x0090': 1}, 'SEND': {'0x0090': 1}})
            self.assertEqual(report['failed_connections'], 0)
            rows = [json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual({row['direction'] for row in rows if row['kind'] == 'tcp_segment'}, {'SEND', 'RECV'})
