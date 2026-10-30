import unittest
from events import PacketEvent
from ipc.protocol import Decoder, encode, HEADER
from parser.framer import FramingError
from storage.database import PacketDatabase


class IPCTests(unittest.TestCase):
    def setUp(self):
        self.event = PacketEvent(1.25, 'SEND', 0x90, b'\x90\x00ab', 'HOOK', 'hook:7')

    def test_fragmented_and_coalesced(self):
        wire = encode(self.event, 7) * 2
        decoder = Decoder({0x90: 4})
        events = []
        for byte in wire:
            events.extend(decoder.feed(bytes([byte])))
        self.assertEqual(events, [self.event] * 2)
        self.assertEqual(Decoder({0x90: 4}).feed(wire), events)

    def test_invalid_header_fails_closed(self):
        decoder = Decoder({0x90: 4})
        with self.assertRaises(ValueError):
            decoder.feed(HEADER.pack(b'GPA1', 65536, 0, 0))
        with self.assertRaises(ValueError):
            decoder.feed(encode(self.event, 7))

    def test_wrong_packet_length_and_unknown_id(self):
        for raw in (b'\x90\x00', b'\xff\xff', b'\x90\x00ab\x90\x00ab'):
            with self.assertRaises((ValueError, FramingError)):
                Decoder({0x90: 4}).feed(HEADER.pack(b'GPA1', len(raw), 0, 7) + raw)

    def test_event_validation_and_storage_compatibility(self):
        with self.assertRaises(ValueError):
            PacketEvent(0, 'SEND', 1, b'\x90\x00', 'HOOK', '')
        db = PacketDatabase(':memory:')
        try:
            db.add(self.event)
            self.assertEqual(db.db.execute('SELECT direction, raw FROM packets').fetchone(),
                             ('SEND', self.event.raw))
        finally:
            db.close()
