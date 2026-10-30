from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from storage.event_trial_selection import save_selection, load_selection, MAX_SELECTION, MAX_LOG_BYTES
from tests.support.event_trials import observation


def raw_log(path, name):
    path.write_text(json.dumps(dict(kind='session_start', schema=1, record_payload=True)) + '\n' +
                    json.dumps(dict(kind='note', name=name)) + '\n', encoding='utf-8')


class EventSelectionTests(unittest.TestCase):
    def test_selection_matches_content_after_log_moves_session_changes_and_global_index_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b, selection = root/'a.jsonl', root/'b.jsonl', root/'selection.json'
            raw_log(a, 'a'); raw_log(b, 'b')
            rows = [observation(0), observation(10, capture_session=1)]
            before = deepcopy(rows)
            save_selection(selection, rows, [0, 1], {0: str(a), 1: str(b)}, 1000)
            doc = json.loads(selection.read_text(encoding='utf-8'))
            self.assertNotIn('packet_index', selection.read_text(encoding='utf-8'))
            moved = root/'moved'; moved.mkdir()
            new_a, new_b = moved/'renamed-a.jsonl', moved/'renamed-b.jsonl'
            a.rename(new_a); b.rename(new_b)
            remapped = [dict(rows[1], capture_session=7, packet_index=999),
                        dict(rows[0], capture_session=9, packet_index=1234)]
            sources = {7: str(new_b), 9: str(new_a)}
            self.assertEqual(load_selection(selection, remapped, sources), ([1, 0], 1000))
            # Stored paths are hints only; loading opens current workspace references.
            doc['sources'][0]['path'] = 'C:/does-not-exist/never-open.jsonl'
            selection.write_text(json.dumps(doc), encoding='utf-8')
            self.assertEqual(load_selection(selection, remapped, sources)[0], [1, 0])
            content = new_b.read_bytes()
            new_b.write_bytes(content + b'{}\n')
            with self.assertRaises(ValueError):
                load_selection(selection, remapped, sources)
            new_b.write_bytes(content)
            changed = deepcopy(remapped); changed[0]['fields']['value'] = 99
            with self.assertRaises(ValueError):
                load_selection(selection, changed, sources)
            duplicate = remapped + [dict(remapped[0], capture_session=12)]
            with self.assertRaises(ValueError):
                load_selection(selection, duplicate, dict(sources, **{'12': str(new_b)}))
            self.assertEqual(rows, before)

    def test_duplicate_event_occurrences_validation_and_failed_save_preserve_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, selection = root/'capture.jsonl', root/'selection.json'
            raw_log(source, 'same')
            rows = [observation(0, packet_index=1), observation(0, packet_index=2)]
            save_selection(selection, rows, [0, 1], {0: str(source)}, 2000)
            original = selection.read_bytes(); doc = json.loads(original)
            self.assertEqual([entry['occurrence'] for entry in doc['anchors']], [0, 1])
            self.assertEqual(load_selection(selection, rows, {0: str(source)}), ([0, 1], 2000))
            with self.assertRaises(ValueError):
                save_selection(source, rows, [0, 1], {0: str(source)}, 2000)
            with patch('storage.event_trial_selection.os.replace', side_effect=OSError('test')), self.assertRaises(OSError):
                save_selection(selection, rows, [0, 1], {0: str(source)}, 2000)
            self.assertEqual(selection.read_bytes(), original)
            self.assertEqual(list(root.glob('*.tmp')), [])
            malformed = []
            for key, value in (('schema_version', True), ('window_ms', True), ('sources', []), ('anchors', [])):
                malformed.append(dict(doc, **{key: value}))
            for field, value in (('source', -1), ('occurrence', 10000), ('event_sha256', 'bad')):
                changed = deepcopy(doc); changed['anchors'][0][field] = value; malformed.append(changed)
            for field, value in (('size', MAX_LOG_BYTES + 1), ('sha256', 'bad'), ('observations_sha256', 'bad')):
                changed = deepcopy(doc); changed['sources'][0][field] = value; malformed.append(changed)
            changed = deepcopy(doc); changed['anchors'][1] = deepcopy(changed['anchors'][0]); malformed.append(changed)
            for changed in malformed:
                with self.subTest(changed=changed):
                    selection.write_text(json.dumps(changed), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_selection(selection, rows, {0: str(source)})
            for content in (b'[]', b'{', b'\xff', b'{"x":1,"x":2}', b'{"x":NaN}',
                            b'[' * 2000, b' ' * (MAX_SELECTION + 1)):
                with self.subTest(length=len(content)):
                    selection.write_bytes(content)
                    with self.assertRaises(ValueError):
                        load_selection(selection, rows, {0: str(source)})
            source.write_text('{}\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                save_selection(selection, rows, [0, 1], {0: str(source)}, 2000)

    def test_versioned_settings_factory_and_legacy_compatibility(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'capture.jsonl'; target=root/'selection.json'
            raw_log(source,'settings')
            rows=[observation(0),observation(10)]
            sources={0:str(source)}
            settings={'mode':'presentation','include_actions':False}
            save_selection(target,rows,[0,1],sources,1000,settings=settings)
            original=target.read_bytes(); doc=json.loads(original)
            self.assertEqual(doc['schema_version'],2)
            seen=[]
            def factory(options):
                seen.append(options)
                return rows
            self.assertEqual(load_selection(target,factory,sources,return_settings=True),([0,1],1000,settings))
            self.assertEqual(seen,[settings])
            for options in ({'mode':'bad','include_actions':False},
                            {'mode':'presentation','include_actions':True},
                            {'mode':'dialogue_start','include_actions':1},
                            {'mode':'presentation'},None):
                broken=dict(doc,comparison=options)
                target.write_text(json.dumps(broken),encoding='utf-8')
                seen.clear()
                with self.assertRaises(ValueError):load_selection(target,factory,sources)
                self.assertEqual(seen,[])
            target.write_bytes(original)
            with self.assertRaises(ValueError):
                save_selection(target,rows,[0,1],sources,1000,settings={'mode':'map_arrival','include_actions':True})
            self.assertEqual(target.read_bytes(),original)
            doc.pop('comparison');doc['schema_version']=1
            target.write_text(json.dumps(doc),encoding='utf-8');seen.clear()
            self.assertEqual(load_selection(target,factory,sources,return_settings=True),([0,1],1000,None))
            self.assertEqual(seen,[None])

    def test_speech_send_navigation_remaps_but_origin_evidence_still_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'capture.jsonl';selection=root/'anchors.json'
            raw_log(source,'speech')
            rows=[observation(0),observation(10),observation(11,kind='player_chat',entity_kind='PLAYER',
                speech_origin={'origin':'send_match_candidate','send_packet_index':100,'send_packet_id':0x8c})]
            save_selection(selection,rows,[0,1],{0:str(source)},1000)
            moved=deepcopy(rows)
            for row in moved:row.update(capture_session=8,packet_index=row['packet_index']+1000)
            moved[2]['speech_origin']['send_packet_index']=1100
            self.assertEqual(load_selection(selection,moved,{8:str(source)}),([0,1],1000))
            moved[2]['speech_origin']['origin']='unresolved'
            with self.assertRaises(ValueError):load_selection(selection,moved,{8:str(source)})
