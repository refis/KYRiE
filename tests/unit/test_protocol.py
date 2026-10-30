import unittest
import tempfile
from pathlib import Path
from parser.definitions import load_lengths
from parser.framer import PacketFramer, FramingError
from capture.tcp_reassembly import TCPReassembler


class TestFraming(unittest.TestCase):
    def test_split_and_join(self):
        framer = PacketFramer({0x90: 7, 0x146: 6, 0x201: -1})
        self.assertEqual(framer.feed(bytes.fromhex('9000b308')), [])
        result = framer.feed(bytes.fromhex('0000014601b3080000'))
        self.assertEqual([pid for pid, _ in result], [0x90, 0x146])
        self.assertEqual(framer.feed(bytes.fromhex('01020700aabbcc')), [(0x201, bytes.fromhex('01020700aabbcc'))])

    def test_unknown_id(self):
        framer = PacketFramer({0x90: 7})
        with self.assertRaises(FramingError):
            framer.feed(bytes.fromhex('ffff'))
        self.assertTrue(framer.failed)

    def test_fragmented_variable_header_and_invalid_length(self):
        framer = PacketFramer({0x201: -1})
        self.assertEqual(framer.feed(b'\x01\x02\x06'), [])
        self.assertEqual(framer.feed(b'\x00ab'), [(0x201, b'\x01\x02\x06\x00ab')])
        with self.assertRaises(FramingError):
            framer.feed(b'\x01\x02\x03\x00')
        with self.assertRaises(FramingError):
            framer.feed(b'\x01\x02\x04\x00')

    def test_retransmit_and_out_of_order(self):
        r = TCPReassembler()
        self.assertEqual(r.feed(100, b'', syn=True), [])
        self.assertEqual(r.feed(105, b'ef'), [])
        self.assertEqual(r.feed(101, b'abcd'), [b'abcd', b'ef'])
        self.assertEqual(r.feed(101, b'abcdef'), [])


class TestDefinitions(unittest.TestCase):
    def test_duplicate_and_conflicting_lengths(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'PacketLength.txt'
            f.write_text('0A09 8\n0A09 8\n0A09 10\n0090 7\n')
            with self.assertWarns(UserWarning):
                definitions = load_lengths(f)
            self.assertEqual(definitions[0x0A09], 10)
            self.assertEqual(definitions[0x0090], 7)


if __name__ == '__main__':
    unittest.main()
