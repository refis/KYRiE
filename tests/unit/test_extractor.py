import struct
import unittest

from tools.extract_packet_lengths import compare, extract


def executable(rows):
    data = bytearray(0x800)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x14c, 1)
    struct.pack_into('<H', data, 0x94, 0xe0)
    struct.pack_into('<H', data, 0x98, 0x10b)
    struct.pack_into('<I', data, 0x98 + 28, 0x400000)
    section = 0x98 + 0xe0
    data[section:section + 8] = b'.text\0\0\0'
    struct.pack_into('<IIII', data, section + 8, 0x400, 0x1000, 0x400, 0x400)
    struct.pack_into('<I', data, section + 36, 0x60000020)
    data[0x400] = 0xc3
    offset = 0x410
    for pid, length, minimum, flag in rows:
        code = bytearray()
        for value in (flag, minimum, length, pid):
            code.extend(b'\x6a' + struct.pack('<b', value) if -128 <= value < 128
                        else b'\x68' + struct.pack('<i', value))
        code.extend(b'\x8b\xce\xe8')
        code.extend(struct.pack('<i', 0x400 - (offset + len(code) + 4)))
        data[offset:offset + len(code)] = code
        offset += len(code)
    return bytes(data)


class ExtractorTests(unittest.TestCase):
    def test_real_instruction_shapes_signed_variable_length_and_duplicates(self):
        data = executable([(0x90, 4, 4, 1), (0x201, -1, 4, 1),
                           (0xc3c, 6, 6, 1), (0x90, 6, 6, 1)])
        lengths, report = extract(data, minimum_records=4)
        self.assertEqual(lengths, {0x90: 6, 0x201: -1, 0xc3c: 6})
        self.assertEqual(report['registrar_va'], 0x401000)
        self.assertEqual(report['registration_count'], 4)
        self.assertEqual(report['duplicates'][0]['previous'], 4)

    def test_invalid_image_and_non_executable_pattern_rejected(self):
        for data in (b'', b'MZ' + bytes(100), executable([])):
            with self.assertRaises(ValueError):
                extract(data, minimum_records=1)
        data = bytearray(executable([(0x90, 4, 4, 1)]))
        struct.pack_into('<I', data, 0x98 + 0xe0 + 36, 0x40000040)
        with self.assertRaises(ValueError):
            extract(bytes(data), minimum_records=1)

    def test_unsupported_attributes_and_invalid_lengths_are_not_definitions(self):
        data = executable([(0x90, 4, 4, 9), (0x91, 1, 1, 1)])
        with self.assertRaises(ValueError):
            extract(data, minimum_records=1)

    def test_negative_registration_attribute_is_preserved(self):
        lengths, report = extract(executable([(0xbbb, -1, 5, -1)]), minimum_records=1)
        self.assertEqual(lengths, {0xbbb: -1})
        self.assertEqual(report['registrations'][0]['attribute'], -1)

    def test_diff_distinguishes_add_change_and_absence(self):
        result = compare({0x90: 4, 0x91: 6}, {0x90: 6, 0xc3c: 6})
        self.assertEqual(result['added'], [{'packet_id': '0x0C3C', 'length': 6}])
        self.assertEqual(result['changed'][0]['previous'], 4)
        self.assertEqual(result['absent_from_extraction'][0]['packet_id'], '0x0091')
