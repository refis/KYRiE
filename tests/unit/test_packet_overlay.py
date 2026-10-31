import json
import struct
import tempfile
import unittest
from pathlib import Path

from events import PacketEvent
from parser.display import DEFAULT_PROFILE, DisplayProfile, ReceiveDisplay
from parser.packet_overlay import (
    INDEX_TAGS, OverlayError, build_packet_entry, fields_from_display_rule,
    find_overlay_packet, format_indexed_value, length_check, load_overlay,
    load_profile_with_overlay, merge_display_document, merge_lengths,
    resolve_index_label, save_overlay, upsert_overlay_packet, validate_overlay,
)
from reconstruction.client_names import empty_client_names
from reconstruction.world import WorldStore
from storage.session_log import SessionLog
from tests.support.world import actor_packet


EXAMPLE = Path(__file__).resolve().parents[2] / 'config' / 'packet_overlay.example.json'


def _overlay_doc(**overrides):
    document = {
        'version': 1,
        'packets': [{
            'id': 'F001',
            'length': 10,
            'name': 'example',
            'fields': {
                'actor_id': {'offset': 2, 'type': 'u32', 'index': 'actor_id'},
                'item_id': {'offset': 6, 'type': 'u16', 'index': 'item_id'},
            },
            'template': '@overlay actor={actor_id} item={item_id};',
        }],
    }
    document.update(overrides)
    return document


class PacketOverlayTests(unittest.TestCase):
    def test_example_overlay_loads_and_merges_lengths(self):
        overlay = load_overlay(EXAMPLE)
        self.assertEqual(overlay['version'], 1)
        self.assertEqual(len(overlay['_sha256']), 64)
        base = {0x90: 4, 0xb4: -1}
        merged = merge_lengths(base, overlay)
        self.assertEqual(merged[0x90], 4)
        self.assertEqual(merged[0xF001], 10)
        self.assertEqual(base[0x90], 4)
        self.assertNotIn(0xF001, base)

    def test_reject_unknown_index_and_version(self):
        with self.assertRaises(OverlayError):
            validate_overlay({'version': 2, 'packets': _overlay_doc()['packets']})
        bad = _overlay_doc()
        bad['packets'][0]['fields']['actor_id']['index'] = 'invented'
        with self.assertRaises(OverlayError):
            validate_overlay(bad)
        self.assertTrue(INDEX_TAGS)

    def test_display_merge_and_index_annotation(self):
        overlay = validate_overlay(_overlay_doc())
        profile = load_profile_with_overlay(DEFAULT_PROFILE, overlay)
        self.assertIn(0xF001, profile.rules)
        self.assertEqual(profile.rules[0xF001]['fields']['actor_id']['index'], 'actor_id')
        names = empty_client_names()
        names['tables']['item_identified']['501'] = '赤ポーション'
        display = ReceiveDisplay(profile, client_names=names)
        raw = struct.pack('<H', 0xF001) + struct.pack('<IH', 42, 501) + struct.pack('<H', 0)
        packet = PacketEvent(1.0, 'RECV', 0xF001, raw, 'NPCAP', 'server-a')
        result = display.decode(packet)
        self.assertEqual(result.status, 'decoded')
        self.assertEqual(result.fields['actor_id'], 42)
        self.assertEqual(result.fields['actor_id_index'], '未観測')
        self.assertEqual(result.fields['item_id'], 501)
        self.assertEqual(result.fields['item_id_index'], '赤ポーション')
        self.assertEqual(format_indexed_value(501, '赤ポーション'), '501（赤ポーション）')

    def test_actor_index_uses_worldstore_name(self):
        world = WorldStore()
        world.begin_capture(1)
        world.apply(actor_packet(actor_id=7, name='試験NPC', connection='flow-a'), session=1, packet_index=0)
        label = resolve_index_label('actor_id', 7, world=world, capture_session=1, connection='flow-a')
        self.assertEqual(label, '試験NPC')
        self.assertEqual(resolve_index_label('actor_id', 99, world=world, capture_session=1, connection='flow-a'), '未観測')
        self.assertEqual(resolve_index_label('item_id', 1, client_names=None), '未登録')

    def test_session_log_records_overlay_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'overlay.json'
            path.write_text(json.dumps(_overlay_doc(), ensure_ascii=False), encoding='utf-8')
            overlay = load_overlay(path)
            definitions = merge_lengths({0x90: 4}, overlay)
            log = SessionLog(folder, definitions, overlay=overlay)
            try:
                used = log.directory / 'PacketOverlay.used.json'
                self.assertTrue(used.is_file())
                snapshot = json.loads(used.read_text(encoding='utf-8'))
                self.assertEqual(snapshot['version'], 1)
                self.assertNotIn('_sha256', snapshot)
                rows = [json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
                start = next(row for row in rows if row['kind'] == 'session_start')
                self.assertEqual(start['overlay_sha256'], overlay['_sha256'])
                self.assertEqual(start['overlay_packet_count'], 1)
                self.assertEqual(
                    (log.directory / 'PacketLength.used.txt').read_text(encoding='utf-8'),
                    '0090 4\nF001 10\n')
            finally:
                log.close()

    def test_display_profile_rejects_bad_index_in_base_json(self):
        document = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        document['packets'][0]['fields'] = dict(document['packets'][0].get('fields') or {})
        first = next(iter(document['packets'][0]['fields']))
        document['packets'][0]['fields'][first]['index'] = 'not_a_tag'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'display.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(Exception):
                DisplayProfile.load(path)

    def test_overlay_replaces_existing_display_id(self):
        base = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        overlay = validate_overlay({
            'version': 1,
            'packets': [{
                'id': '00B4',
                'length': -1,
                'name': 'overlay_mes',
                'fields': {
                    'actor_id': {'offset': 4, 'type': 'u32', 'index': 'actor_id'},
                    'text': {'offset': 8, 'type': 'string'},
                },
                'template': 'OVERLAY {actor_id}: {text}',
                'min_length': 9,
            }],
        })
        merged = merge_display_document(base, overlay)
        ids = [pid for rule in merged['packets'] for pid in rule['ids']]
        self.assertEqual(ids.count('00B4'), 1)
        profile = DisplayProfile(merged)
        display = ReceiveDisplay(profile)
        body = struct.pack('<I', 9) + b'hi\0'
        # 00B4 variable: id + length + actor + text
        raw = struct.pack('<HH', 0xb4, 4 + len(body)) + body
        result = display.decode(PacketEvent(1.0, 'RECV', 0xb4, raw, 'NPCAP', 'c'))
        self.assertEqual(result.text, 'OVERLAY 9: hi')
        self.assertEqual(result.fields['actor_id_index'], '未観測')

    def test_editor_helpers_upsert_save_and_length_check(self):
        entry = build_packet_entry(
            0xF001, 10, 'edited',
            {'actor_id': {'offset': 2, 'type': 'u32', 'index': 'actor_id'},
             'item_id': {'offset': 6, 'type': 'u16', 'index': 'item_id'}},
            template='@overlay actor={actor_id} item={item_id};',
            min_length=10,
        )
        notes = length_check(10, 10, entry['fields'])
        self.assertTrue(any('一致' in note for note in notes))
        notes_mismatch = length_check(8, 10, entry['fields'])
        self.assertTrue(any('不一致' in note for note in notes_mismatch))
        base = validate_overlay(_overlay_doc())
        updated = upsert_overlay_packet(base, entry)
        self.assertEqual(len(updated['packets']), 1)
        self.assertEqual(find_overlay_packet(updated, 0xF001)['name'], 'edited')
        second = build_packet_entry(0xF002, 4, 'other', {'flag': {'offset': 2, 'type': 'u16'}},
                                    template='@overlay other={flag};')
        updated = upsert_overlay_packet(updated, second)
        self.assertEqual(len(updated['packets']), 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'overlay.json'
            saved = save_overlay(path, updated)
            self.assertEqual(saved['_sha256'], load_overlay(path)['_sha256'])
            rule = dict(name='from_display', fields={'actor_id': {'offset': 4, 'type': 'u32', 'index': 'actor_id'}})
            self.assertEqual(fields_from_display_rule(rule)['actor_id']['index'], 'actor_id')


if __name__ == '__main__':
    unittest.main()
