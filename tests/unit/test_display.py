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
        self.assertEqual(display.decode(event(0x142, struct.pack('<I', 42))).text, 'input .@num;')
        self.assertEqual(display.decode(event(0x1D4, struct.pack('<I', 42))).text, 'input .@str$;')
        self.assertNotIn("'@", text)

    def test_rathena_generation_profiles_exist_with_matched_status_ids(self):
        root = Path(__file__).resolve().parents[2]
        for name in ('dialogue.json', 'entity_metadata.json', 'shops.json', 'mob_skills.json',
                     'mob_skill_configured.json', 'mob_spawns.json', 'mob_spawn_configured.json',
                     'event_timers.json', 'script_commands.json', 'status_ids.json',
                     'identity_protection.json'):
            path = root / 'config' / 'rathena' / name
            self.assertTrue(path.is_file(), name)
            json.loads(path.read_text(encoding='utf-8'))
        status = json.loads((root / 'config' / 'rathena' / 'status_ids.json').read_text(encoding='utf-8'))
        self.assertEqual(status['target'], 'rathena')
        self.assertEqual(status['source']['commit'], 'd4b8e7b8f16061cc2496d377ac8f777ce72a4f39')
        self.assertEqual(len(status['entries']), 888)
        self.assertEqual(set(status['ambiguous']), {'112', '149', '324', '438', '737', '1316'})
        self.assertEqual(status['entries']['12']['symbol'], 'SC_INCREASEAGI')
        self.assertEqual(status['entries']['12']['script_id'], 32)
        self.assertEqual(status['entries']['12']['argument_policy'], 'review')
        self.assertEqual(status['entries']['12']['adoption'], 'user_policy')
        self.assertEqual(status['entries']['50']['symbol'], 'SC_STRIPWEAPON')
        self.assertEqual(status['entries']['50']['script_id'], 68)
        self.assertEqual(status['entries']['50']['argument_policy'], 'review')
        self.assertIn('12', status['excluded_candidates'])
        self.assertIn('50', status['excluded_candidates'])
        self.assertEqual(status['entries']['621']['argument_policy'], 'val1_only')
        self.assertEqual(status['entries']['665']['argument_policy'], 'val1_only')
        dialogue = json.loads((root / 'config' / 'rathena' / 'dialogue.json').read_text(encoding='utf-8'))
        self.assertNotIn('getmdmapname', json.dumps(dialogue))
        self.assertIn('instance_mapname', dialogue['instance_map_reference'])
        self.assertEqual(dialogue['number'], 'input .@gpa_number;')
        self.assertEqual(dialogue['text'], 'input .@gpa_text$;')
        self.assertNotIn("'@", json.dumps(dialogue))

    def test_rathena_display_sc_end_converts_icon_ids_and_keeps_unresolved_as_comments(self):
        from pathlib import Path
        rathena_path = Path(__file__).resolve().parents[2] / 'config' / 'rathena' / 'display.json'
        display = ReceiveDisplay(DisplayProfile.load(rathena_path))
        # Adopted icons 12/50 must emit converted SC IDs, never raw icons.
        for icon, script_id, symbol in ((12, 32, 'SC_INCREASEAGI'), (50, 68, 'SC_STRIPWEAPON')):
            result = display.decode(event(0x196, struct.pack('<HIB', icon, 42, 0)))
            self.assertEqual(result.status, 'decoded')
            self.assertEqual(result.fields['effect_id'], icon)
            self.assertEqual(result.fields['status_script_id'], script_id)
            self.assertTrue(result.fields['status_mapped'])
            self.assertEqual(result.text, f'sc_end {script_id},42;\t// icon {icon} {symbol}')
            self.assertNotIn(f'sc_end {icon},', result.text)
        # Existing non-identity mapping (icon != script_id).
        status = json.loads((Path(__file__).resolve().parents[2] / 'config' / 'rathena' / 'status_ids.json').read_text(encoding='utf-8'))
        icon, row = next((int(key), value) for key, value in status['entries'].items()
                         if int(key) != value['script_id'] and int(key) not in (12, 50))
        result = display.decode(event(0x196, struct.pack('<HIB', icon, 7, 0)))
        self.assertEqual(result.text, f'sc_end {row["script_id"]},7;\t// icon {icon} {row["symbol"]}')
        self.assertNotIn(f'sc_end {icon},', result.text)
        # Remaining ambiguous / unknown icons must not become executable sc_end.
        for icon in (112, 149, 324, 438, 737, 1316, 65535):
            result = display.decode(event(0x196, struct.pack('<HIB', icon, 9, 0)))
            self.assertTrue(result.text.startswith('@status_end_unresolved'))
            self.assertNotIn('sc_end ', result.text)
            self.assertEqual(result.fields['effect_id'], icon)
            self.assertFalse(result.fields['status_mapped'])

    def test_send_crypto_keying_packets_display_without_claiming_decrypt(self):
        from parser.definitions import load_lengths
        lengths = load_lengths(Path(__file__).resolve().parents[2] / 'PacketLength.txt')
        self.assertEqual(lengths[0x2A3], 18)
        self.assertEqual(lengths[0x2BD], 10)
        lingo = self.display.decode(event(0x2A3, struct.pack('<IIII', 1, 2, 3, 4)))
        self.assertEqual(lingo.status, 'decoded')
        self.assertEqual(lingo.fields['alg_num'], 1)
        self.assertIn('@send_crypto_lingo_key', lingo.text)
        self.assertIn('decrypt unresolved', lingo.text)
        deform = self.display.decode(event(0x2BD, struct.pack('<II', 5, 6)))
        self.assertEqual(deform.status, 'decoded')
        self.assertEqual(deform.fields['seed'], 5)
        self.assertEqual(deform.fields['add'], 6)
        self.assertIn('@send_crypto_deform_key', deform.text)

