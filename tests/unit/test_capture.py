import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from scapy.all import Ether, IP, IPv6, TCP, Raw, Padding
from capture.receiver import Receiver
from capture.process_monitor import Endpoint
from capture.tcp_reassembly import TCPReassembler


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.events, self.status = [], []
        self.r = Receiver('', None, {0x90: 4}, self.events.append, self.status.append)

    def send(self, seq, payload=b'', flags='A', remote='10.0.0.1'):
        self.r._handle(IP(src=remote, dst='10.0.0.2') /
                       TCP(sport=6900, dport=50000, seq=seq, flags=flags) / Raw(payload))

    def test_syn_retransmission_keeps_partial_packet(self):
        self.send(100, flags='SA')
        self.send(101, b'\x90\x00')
        self.send(100, flags='SA')
        self.send(103, b'ab')
        self.assertEqual([e.raw for e in self.events], [b'\x90\x00ab'])

    def test_multiple_servers_and_reconnect(self):
        for remote in ('10.0.0.1', '10.0.0.3'):
            self.send(100, flags='SA', remote=remote)
            self.send(101, b'\x90\x00ab', remote=remote)
        self.send(500, flags='SA')
        self.send(501, b'\x90\x00cd')
        self.assertEqual(len(self.events), 3)
        self.assertNotEqual(self.events[0].connection, self.events[2].connection)

    def test_unknown_and_midstream_never_resynchronize(self):
        self.send(101, b'\x90\x00ab')
        self.send(100, flags='SA')
        self.send(101, b'\xff\xff')
        self.send(103, b'\x90\x00ab')
        self.assertEqual(self.events, [])

    def test_discovery_filters_and_removes_connections(self):
        self.r = Receiver('ignored', 'invalid', {0x90: 4}, self.events.append,
                          self.status.append, process_pid=42)
        endpoint = Endpoint('10.0.0.2', 50000, '10.0.0.1', 6900, 42, 'ESTABLISHED')
        self.send(100, flags='SA')
        with patch('capture.receiver.discover', return_value={endpoint}):
            self.r.refresh_connections()
        self.send(101, b'\x90\x00ab')
        self.assertEqual(len(self.events), 1)
        with patch('capture.receiver.discover', return_value=set()):
            self.r.refresh_connections()
        self.assertFalse(self.r.connections)

    def test_gap_timeout_stops_only_affected_stream(self):
        self.send(100, flags='SA')
        self.send(103, b'ab')
        with patch('capture.receiver.time.monotonic', return_value=10**12):
            self.r.refresh_connections()
        self.send(101, b'\x90\x00')
        self.assertFalse(self.events)
        self.assertIn('gap timeout', self.status[-1])

    def test_sequence_wrap_and_conflicting_overlap(self):
        r = TCPReassembler()
        r.feed(0xfffffffd, b'', syn=True)
        self.assertEqual(r.feed(0xfffffffe, b'ab'), [b'ab'])
        self.assertEqual(r.feed(0, b'cd'), [b'cd'])
        r.feed(5, b'abc')
        r.feed(6, b'XX')
        self.assertTrue(r.failed)

    def test_pending_limit(self):
        r = TCPReassembler(max_pending=2)
        r.feed(0, b'', syn=True)
        r.feed(10, b'abc')
        self.assertTrue(r.failed)
        self.assertFalse(r.pending)

    def test_discovery_failure_revokes_stale_ownership(self):
        self.r.process_pid = 42
        key = ('10.0.0.1', 6900, '10.0.0.2', 50000)
        self.r.allowed.add(key)
        self.send(100, flags='SA')
        with patch('capture.receiver.discover', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.r.refresh_connections()
        self.send(101, b'\x90\x00ab')
        self.assertFalse(self.events)
        self.assertFalse(self.r.connections)

    def test_explicit_existing_connection_attachment(self):
        self.r.allow_midstream = True
        self.send(101, b'\x90')
        self.send(102, b'\x00ab')
        self.send(101, b'\x90\x00ab')
        self.assertEqual([e.raw for e in self.events], [b'\x90\x00ab'])
        self.assertIn('ASSUMED=101', self.events[0].connection)
        self.assertEqual(self.r.diagnostics()['assumed_boundaries'], 1)

    def test_attach_does_not_scan_or_restart_after_unknown_id(self):
        self.r.allow_midstream = True
        self.send(101, b'\xff\xff\x90\x00ab')
        self.send(107, b'\x90\x00ab')
        self.assertFalse(self.events)
        self.assertEqual(self.r.diagnostics()['framing_errors'], 1)
        self.send(500, flags='SA')
        self.send(501, b'\x90\x00cd')
        self.assertEqual([e.raw for e in self.events], [b'\x90\x00cd'])
        self.assertIn('SYN=500', self.events[0].connection)

    def test_strict_mode_reports_received_payload_waiting_for_syn(self):
        self.send(101, b'\x90\x00ab')
        self.send(105, b'\x90\x00cd')
        self.assertEqual(len(self.status), 1)
        self.assertIn('reconnect', self.status[0])
        self.assertEqual(self.r.diagnostics()['waiting_syn_segments'], 2)
        self.assertEqual(self.r.diagnostics()['matched_payload_bytes'], 8)

    def test_early_payload_replayed_after_process_discovery(self):
        self.r.process_pid = 42
        endpoint = Endpoint('10.0.0.2', 50000, '10.0.0.1', 6900, 42, 'ESTABLISHED')
        self.send(100, flags='SA')
        self.send(103, b'ab')
        self.send(101, b'\x90\x00')
        self.assertFalse(self.events)
        self.assertEqual(self.r.diagnostics()['early_bytes'], 4)
        with patch('capture.receiver.discover', return_value={endpoint}):
            self.r.refresh_connections()
        self.assertEqual([e.raw for e in self.events], [b'\x90\x00ab'])
        self.assertEqual(self.r.diagnostics()['early_bytes'], 0)
        self.assertEqual(self.r.early_count, 0)

    def test_early_overflow_discards_boundary_instead_of_missing_prefix(self):
        self.r.process_pid = 42
        self.r.max_early_bytes = 3
        endpoint = Endpoint('10.0.0.2', 50000, '10.0.0.1', 6900, 42, 'ESTABLISHED')
        self.send(100, flags='SA')
        self.send(101, b'\x90\x00ab')
        self.assertEqual(self.r.diagnostics()['early_overflows'], 1)
        with patch('capture.receiver.discover', return_value={endpoint}):
            self.r.refresh_connections()
        self.send(105, b'\x90\x00cd')
        self.assertFalse(self.events)
        self.assertFalse(self.r.syn_seen)

    def test_early_cache_expires_without_socket_discovery(self):
        self.r.process_pid = 42
        with patch('capture.receiver.time.monotonic', return_value=1):
            self.send(100, flags='SA')
            self.send(101, b'\x90\x00ab')
        with patch('capture.receiver.time.monotonic', return_value=32):
            self.send(105, b'\x90\x00cd')
        self.assertFalse(self.r.early_segments)
        self.assertEqual(self.r.early_bytes, 0)

    def test_auto_interfaces_and_ready_callback(self):
        adapters = [SimpleNamespace(name='Ethernet'), SimpleNamespace(name='WiFi')]
        with patch('capture.receiver.get_working_ifaces', return_value=adapters), \
             patch('capture.receiver.AsyncSniffer') as sniffer:
            self.r.start()
            self.assertEqual(sniffer.call_args.kwargs['iface'], adapters)
            self.assertFalse(self.r.ready)
            sniffer.call_args.kwargs['started_callback']()
            self.assertTrue(self.r.ready)

    def test_explicit_interface_and_no_interface_error(self):
        self.r.iface = 'chosen-adapter'
        with patch('capture.receiver.AsyncSniffer') as sniffer:
            self.r.start()
            self.assertEqual(sniffer.call_args.kwargs['iface'], ['chosen-adapter'])
        self.r.sniffer = None
        self.r.iface = None
        with patch('capture.receiver.get_working_ifaces', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'No usable Npcap interfaces'):
                self.r.start()

    def test_sniffer_startup_failure_surfaces_and_cleans_up(self):
        self.r.sniffer = SimpleNamespace(exception=PermissionError('capture denied'), running=True,
                                         thread=Mock(is_alive=Mock(return_value=False)))
        with self.assertRaisesRegex(RuntimeError, 'capture denied'):
            self.r.check_health()
        self.r.stop()
        self.assertIsNone(self.r.sniffer)
        self.assertFalse(self.r.connections)

    def test_stop_during_startup_cancels_on_ready(self):
        sniffer = SimpleNamespace(running=True, start=Mock(), stop=Mock())
        with patch('capture.receiver.get_working_ifaces', return_value=['adapter']), \
             patch('capture.receiver.AsyncSniffer', return_value=sniffer) as factory:
            self.r.start()
            callback = factory.call_args.kwargs['started_callback']
            self.r.stop()
            callback()
        sniffer.stop.assert_called_once_with(join=False)
        self.assertFalse(self.r.ready)

    def padded_frame(self, seq, payload=b'', flags='A', padding=bytes(6), ipv6=False):
        network = (IPv6(src='::1', dst='::2') if ipv6 else
                   IP(src='10.0.0.1', dst='10.0.0.2'))
        frame = (Ether(src='00:00:00:00:00:01', dst='00:00:00:00:00:02') /
                 network / TCP(sport=6900, dport=50000, seq=seq, flags=flags))
        if payload:
            frame = frame / Raw(payload)
        # Serialize and dissect: the IP length excludes these trailing bytes.
        packet = Ether(bytes(frame) + padding)
        self.assertIsNotNone(packet.getlayer(Padding))
        return packet

    def test_ethernet_padding_on_syn_ack_consumes_no_sequence_bytes(self):
        self.r.definitions = {0: 2, 0x90: 4}
        self.r._handle(self.padded_frame(100, flags='SA'))
        self.assertEqual(self.events, [])
        stream, _ = next(iter(self.r.connections.values()))
        self.assertEqual(stream.next_seq, 101)
        self.r._handle(self.padded_frame(101, b'\x90\x00ab', padding=bytes(2)))
        self.assertEqual([e.packet_id for e in self.events], [0x90])
        self.assertEqual(self.events[0].raw, b'\x90\x00ab')
        self.assertEqual(stream.next_seq, 105)

    def test_pure_ack_padding_neither_frames_nor_creates_unknown_id_error(self):
        self.r.definitions = {0: 2, 0x90: 4}
        self.send(100, flags='SA')
        for padding in (bytes(6), bytes.fromhex('acac00000000'), b'1.' + bytes(17)):
            self.r._handle(self.padded_frame(101, padding=padding))
        self.assertFalse(self.events)
        self.assertEqual(self.r.stats['framing_errors'], 0)
        self.assertEqual(self.r.stats['matched_payload_bytes'], 0)
        self.send(101, b'\x90\x00ab')
        self.assertEqual(len(self.events), 1)

    def test_padding_cannot_trigger_existing_connection_attachment(self):
        self.r.allow_midstream = True
        self.r.definitions = {0: 2, 0x90: 4}
        self.r._handle(self.padded_frame(101))
        self.assertFalse(self.r.connections)
        self.assertFalse(self.events)
        self.assertEqual(self.r.stats['assumed_boundaries'], 0)
        self.r._handle(self.padded_frame(101, b'\x90\x00ab', padding=bytes(2)))
        self.assertEqual([e.packet_id for e in self.events], [0x90])

    def test_real_zero_packet_and_trailing_zero_data_are_preserved(self):
        self.r.definitions = {0: 2, 0x90: 4}
        self.send(100, flags='SA')
        self.r._handle(self.padded_frame(101, b'\x90\x00\x00\x00\x00\x00', padding=bytes(4)))
        self.assertEqual([(e.packet_id, e.raw) for e in self.events],
                         [(0x90, b'\x90\x00\x00\x00'), (0, b'\x00\x00')])

    def test_pre_discovery_cache_excludes_padding(self):
        self.r.process_pid = 42
        endpoint = Endpoint('10.0.0.2', 50000, '10.0.0.1', 6900, 42, 'ESTABLISHED')
        self.r._handle(self.padded_frame(100, flags='SA'))
        self.r._handle(self.padded_frame(101))
        self.r._handle(self.padded_frame(101, b'\x90\x00ab', padding=bytes(2)))
        self.assertEqual(self.r.early_bytes, 4)
        with patch('capture.receiver.discover', return_value={endpoint}):
            self.r.refresh_connections()
        self.assertEqual([e.raw for e in self.events], [b'\x90\x00ab'])

    def test_ipv6_padding_is_excluded(self):
        self.r._handle(self.padded_frame(100, flags='SA', ipv6=True))
        self.r._handle(self.padded_frame(101, b'\x90\x00ab', ipv6=True))
        self.assertEqual([e.raw for e in self.events], [b'\x90\x00ab'])
