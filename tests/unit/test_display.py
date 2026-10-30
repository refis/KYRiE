from tests.support.display import event, variable
import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path

from parser.display import DEFAULT_PROFILE, DEFAULT_SEND_PROFILE, DisplayProfile, ProfileError, ReceiveDisplay






class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.profile = DisplayProfile.load()
        self.display = ReceiveDisplay(self.profile)

    def test_japanese_dialogue_and_escaping(self):
        raw = struct.pack('<I', 42) + 'こんにちは「テスト」"\\\n'.encode('cp932') + b'\0'
        packet = variable(0xB4, raw)
        result = self.display.decode(packet)
        self.assertEqual(result.status, 'decoded')
        self.assertEqual(result.fields['actor_id'], 42)
        self.assertEqual(result.text, 'mes "こんにちは「テスト」\\"\\\\\\n";')
        self.assertEqual(packet.raw, variable(0xB4, raw).raw)

    def test_typed_dialogue_starts_after_type(self):
        result = self.display.decode(variable(0x972, struct.pack('<IB', 42, 7) + '本文'.encode('cp932') + b'\0'))
        self.assertEqual(result.text, 'mes "本文";\t//type:7')
        self.assertEqual(result.fields['kind'], 7)

    def test_nul_and_no_nul_strings(self):
        for text in (b'hello', b'hello\0ignored'):
            self.assertEqual(self.display.decode(variable(0x8E, text)).fields['text'], 'hello')

    def test_invalid_encoding_is_visible_and_next_packet_survives(self):
        result = self.display.decode(variable(0xB4, struct.pack('<I', 42) + b'\x81'))
        self.assertEqual(result.status, 'error')
        self.assertIn('@decode_error', result.text)
        self.assertEqual(self.display.decode(event(0xB5, struct.pack('<I', 42))).text, 'next;')

    def test_short_fields_fail_without_reading_or_updating_state(self):
        result = self.display.decode(event(0x91, b'broken'))
        self.assertEqual(result.status, 'error')
        self.assertEqual(self.display.states, {})

    def test_fixed_string_with_no_nul_keeps_last_character(self):
        result = self.display.decode(event(0x7FE, b'abcdefghijklmnopqrstuvwx'))
        self.assertEqual(result.text, 'musiceffect "abcdefghijklmnopqrstuvwx";')

    def test_connection_scoped_cutin_state(self):
        close = event(0xB6, struct.pack('<I', 42))
        self.assertEqual(self.display.decode(close).text, 'close;')
        self.display.decode(event(0x1B3, b'image'.ljust(64, b'\0') + b'\x01'))
        self.assertEqual(self.display.decode(close).text, 'close;')
        self.assertEqual(self.display.decode(event(0xB6, struct.pack('<I', 42), 'server-b')).text, 'close;')
        self.display.decode(event(0x1B3, bytes(64) + b'\xff'))
        self.assertEqual(self.display.decode(close).text, 'close;')
        self.display.reset()
        self.assertFalse(self.display.states)

    def test_map_context_and_little_endian_coordinates(self):
        self.display.decode(event(0x91, b'prontera.gat'.ljust(16, b'\0') + struct.pack('<HH', 150, 200)))
        self.assertEqual(self.display.decode(event(0x1D6, struct.pack('<H', 4))).text,
                         '@mapproperty map: prontera.gat, type: 4')
        result = self.display.decode(event(0xBA3, struct.pack('<II', 300, 400)))
        self.assertEqual(result.text, 'mespos 300,400;')

    def test_color_and_variant(self):
        default = struct.pack('<IHHHH', 0xff1122, 400, 12, 0, 0)
        result = self.display.decode(variable(0x1C3, default + b'hello\0'))
        self.assertEqual(result.text, 'announce "hello", 0x9, 0xff1122;')

    def test_64_bit_experience_and_numeric_transforms(self):
        result = self.display.decode(event(0xACC, struct.pack('<IQHH', 42, 2**40, 1, 0)))
        self.assertEqual(result.text, 'getexp 1099511627776,0,0;')
        self.assertEqual(self.display.decode(event(0xA36, struct.pack('<IB', 42, 19))).fields['percent'], 95)
        self.assertEqual(self.display.decode(event(0xAB9, struct.pack('<H', 5))).text, 'itempreview 3;')

    def test_unknown_display_does_not_change_framing_or_send(self):
        result = self.display.decode(event(0xFFFF, b'anything'))
        self.assertEqual(result.status, 'unmapped')
        self.assertIn('0xFFFF', result.text)
        self.assertEqual(self.display.decode(event(0xB5, bytes(4), direction='SEND')).status, 'skipped')

    def test_external_edit_changes_output_without_python_change(self):
        document = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        document['packets'][0]['template'] = 'NPC {actor_id}: {text}'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'display.json'
            path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            display = ReceiveDisplay(DisplayProfile.load(path))
            self.assertEqual(display.decode(variable(0xB4, struct.pack('<I', 42) + b'hello\0')).text,
                             'NPC 42: hello')

    def test_reject_bad_profiles_before_capture(self):
        original = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        for template in ('{missing}', '{text.__class__}', '{text[0]}', '{text!r}', '{text:10000000}', '{actor_id:{length}}', '{text:04X}'):
            document = copy.deepcopy(original)
            document['packets'][0]['template'] = template
            with self.subTest(template=template), self.assertRaises(ProfileError):
                DisplayProfile(document)
        for decoder in ('execute', {}):
            document = copy.deepcopy(original)
            document['packets'][0]['decoder'] = decoder
            with self.subTest(decoder=decoder), self.assertRaises(ProfileError):
                DisplayProfile(document)
        for field in ({'offset': -1, 'type': 'u32'}, {'offset': 4, 'type': 'pointer'},
                      {'offset': 4, 'type': 'string', 'encoding': 'missing-codec'},
                      {'offset': 4, 'type': 'string', 'encoding': 'hex_codec'}):
            document = copy.deepcopy(original)
            document['packets'][0]['fields']['text'] = field
            with self.subTest(field=field), self.assertRaises(ProfileError):
                DisplayProfile(document)

    def test_duplicate_display_ids_and_json_keys_rejected(self):
        document = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        document['packets'].append(copy.deepcopy(document['packets'][0]))
        with self.assertRaises(ProfileError):
            DisplayProfile(document)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'display.json'
            path.write_text('{"version":1,"version":1}', encoding='utf-8')
            with self.assertRaises(ProfileError):
                DisplayProfile.load(path)

    def test_send_profile_uses_separate_direction_and_decodes_action_and_chat(self):
        display = ReceiveDisplay(DisplayProfile.load(DEFAULT_SEND_PROFILE), direction='SEND')
        action = event(0x89, struct.pack('<IB', 42, 7), direction='SEND')
        self.assertEqual(display.decode(action).text, 'SEND actor_action target=42, type=7')
        self.assertEqual(display.decode(event(0x89, struct.pack('<IB', 42, 7))).status, 'skipped')
        text = 'こんにちは'.encode('cp932') + b'\0'
        packet = event(0x8C, struct.pack('<H', 4 + len(text)) + text, direction='SEND')
        self.assertEqual(display.decode(packet).text, 'SEND public_chat "こんにちは"')

    def test_rathena_display_covers_auriga_packet_ids_without_auriga_instance_commands(self):
        from tests.support.world import map_packet
        root = Path(__file__).resolve().parents[2]
        auriga = json.loads((root / 'config' / 'auriga' / 'display.json').read_text(encoding='utf-8'))
        rathena_path = root / 'config' / 'rathena' / 'display.json'
        document = json.loads(rathena_path.read_text(encoding='utf-8'))
        auriga_ids = {packet_id for packet in auriga['packets'] for packet_id in packet['ids']}
        rathena_ids = {packet_id for packet in document['packets'] for packet_id in packet['ids']}
        self.assertEqual(rathena_ids, auriga_ids)
        self.assertFalse(document.get('entity_metadata'))
        for key in ('instance_warp', 'instance_entry_warp', 'instance_map_reference'):
            self.assertNotIn(key, document)
        text = rathena_path.read_text(encoding='utf-8')
        self.assertNotIn('getmdmapname', text)
        self.assertNotIn('mdenter', text)
        display = ReceiveDisplay(DisplayProfile.load(rathena_path))
        self.assertEqual(display.decode(variable(0xB4, struct.pack('<I', 42) + 'hi'.encode('cp932') + b'\0')).text,
                         'mes "hi";')
        self.assertEqual(display.decode(map_packet('1@toy.gat')).text, 'warp "1@toy.gat", 100, 120;')
        self.assertTrue(display.decode(event(0xBA2, struct.pack('<II', 10, 20))).text.startswith('// messize'))

