import struct
import unittest

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from tests.support.dialogue import packet, music_event


class MusicObservationTests(unittest.TestCase):
    def test_unassigned_music_participates_in_window_variants_without_target_or_timer_inference(self):
        from copy import deepcopy
        from tests.support.event_trials import observation
        from reconstruction.event_trials import compare_event_trials, announcement_in_scope
        from reconstruction.event_timer_export import build_timer_candidate
        def music(time, name='theme.mp3', mode=None, **changes):
            return observation(time, kind='music', actor_id=None, target_observed=False, entity_kind='unresolved',
                npc={}, fields=dict(music=name, mode=mode), **changes)
        for changed in ('name', 'mode', 'missing'):
            rows = [observation(0), music(1), music(1.1, 'other-flow.mp3', flow_id='other'), observation(10)]
            if changed != 'missing':
                rows.append(music(11, name='changed.mp3' if changed == 'name' else 'theme.mp3',
                                  mode=255 if changed == 'mode' else None, context='during_dialogue'))
            before = deepcopy(rows)
            report = compare_event_trials(rows, [0, 3], window_ms=2000)
            self.assertEqual(report['status'], 'observed_difference')
            self.assertEqual(len(report['trials'][0]['events']), 2)
            event = report['trials'][0]['events'][1]
            self.assertEqual(event['association_basis'], 'selected_timer_window_same_flow')
            self.assertFalse(event['observation']['target_observed'])
            self.assertFalse(announcement_in_scope(rows[1], rows[0]))
            with self.assertRaises(ValueError):
                build_timer_candidate(report, 0, [100, 1100], confirmed=True)
            self.assertEqual(rows, before)

    def test_music_comparison_excludes_other_capture_map_and_map_generation(self):
        from tests.support.event_trials import observation
        from reconstruction.event_trials import compare_event_trials
        anchor = observation(0)
        def music(time, **changes):
            return observation(time, kind='music', actor_id=None, target_observed=False, entity_kind='unresolved',
                npc={}, fields=dict(music='theme.mp3', mode=None), **changes)
        context = dict(map_name=anchor['npc']['map_name'], map_generation=anchor['npc']['map_generation'])
        rows = [anchor, music(1, map_context=context), music(1.2, capture_session=1),
                music(1.3, map_context=dict(context, map_name='other.gat')),
                music(1.4, map_context=dict(context, map_generation=2)), observation(10), music(11, map_context=context)]
        report = compare_event_trials(rows, [0, 5], window_ms=2000)
        self.assertEqual([len(trial['events']) for trial in report['trials']], [2, 2])
        self.assertEqual(len(report['variants']), 1)

    def test_music_is_unassigned_and_preserves_numeric_input_and_close(self):
        store = DialogueStore()
        records = [music_event(), packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                   packet(0x142, struct.pack('<I', 42)), music_event('曲名.mp3', 255),
                   packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'),
                   packet(0xb6, struct.pack('<I', 42)), music_event('', 0),
                   packet(0x146, struct.pack('<I', 42), 'SEND'), music_event('end.mp3')]
        for record in records:
            store.apply(record)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows],
                         ['outside_dialogue', 'during_dialogue', 'close_wait', 'outside_dialogue'])
        self.assertTrue(all(row['actor_id'] is None and not row['target_observed'] and row['npc'] == {}
                            for row in rows))
        self.assertEqual(rows[0]['fields'], {'music': 'theme.mp3', 'mode': None})
        self.assertEqual(rows[1]['fields'], {'music': '曲名.mp3', 'mode': 255})
        self.assertEqual(rows[2]['fields']['music'], '')
        self.assertEqual(len(store.sessions), 1)
        self.assertEqual(store.sessions[0].steps[2]['reply_to'], 1)
        code = AurigaRenderer().render(store.sessions[0])
        self.assertNotIn('musiceffect', code)
        self.assertNotIn('close2;', code)

    def test_exact_layout_cp932_and_direction_are_validated(self):
        for event in (packet(0x7fe, b'secret.mp3'),
                      packet(0xb8c, struct.pack('<H', 7) + b'\x00a'),
                      packet(0x7fe, b'\x81\0'.ljust(24, b'\0'))):
            with self.subTest(pid=event.packet_id):
                store = DialogueStore()
                store.apply(event)
                self.assertEqual(store.issue_count, 1)
                self.assertFalse(store.presentation_observations)
                self.assertNotIn('secret', str(store.issues))
        full = packet(0x7fe, b'a' * 24)
        self.assertEqual(decode_dialogue(full)[2]['music'], 'a' * 24)
        self.assertIsNone(decode_dialogue(packet(0x7fe, bytes(24), 'SEND')))

    def test_presentation_notes_separate_sound_origin_and_unrecorded_targets_without_mutation(self):
        from copy import deepcopy
        from gui.presentation_context import presentation_context
        rows=[dict(kind='sound',packet_id=0x1d3,actor_id=42,context='during_dialogue'),
              dict(kind='music',packet_id=0x7fe,actor_id=None,context='during_dialogue'),
              dict(kind='progressbar',packet_id=0x2f0,actor_id=None,context='outside_dialogue'),
              dict(kind='progressbar',packet_id=0x9d1,actor_id=42,context='outside_dialogue'),
              dict(kind='progress_action',packet_id=0x2f0,actor_id=42,comparison_scope='dialogue_owner',context='during_dialogue')]
        before=deepcopy(rows)
        notes=[presentation_context(row) for row in rows]
        self.assertEqual([note['actor_role'] for note in notes],['sound_origin','not_recorded','not_recorded','progress_target','not_recorded'])
        self.assertEqual(notes[0]['observed_actor_id'],42)
        self.assertIsNone(notes[4]['observed_actor_id'])
        self.assertEqual(notes[4]['dialogue_owner_actor_id'],42)
        self.assertIsNone(notes[3]['player_context_required'])
        self.assertTrue(all(not note['automatic_timer_supported'] and not note['cause_confirmed'] for note in notes))
        self.assertEqual(rows,before)
        self.assertIsNone(presentation_context({'kind':'emotion'}))


class MapCellObservationTests(unittest.TestCase):
    def cell(self, cell_type=1):
        return packet(0x192, struct.pack('<HHH', 100, 200, cell_type) + b'test.gat'.ljust(16,b'\0'))

    def test_cell_is_strict_observation_without_actor_or_dialogue_commands(self):
        from copy import deepcopy
        from dataclasses import replace
        event = self.cell(65535)
        self.assertEqual(decode_dialogue(event), ('mapcell',None,
            dict(x=100,y=200,cell_type=65535,map_name='test.gat')))
        self.assertIsNone(decode_dialogue(replace(event,direction='SEND')))
        for raw in (event.raw[:-1],event.raw+b'\0'):
            with self.assertRaises(ValueError):
                decode_dialogue(replace(event,raw=raw))
        store=DialogueStore()
        store.apply(event)
        self.assertEqual(store.sessions,[])
        store.apply(packet(0x90,struct.pack('<IB',42,1),'SEND'))
        store.apply(packet(0xb4,struct.pack('<I',42)+b'hello\0'))
        before=deepcopy(store.sessions[0])
        store.apply(event)
        self.assertEqual(store.sessions[0],before)
        self.assertEqual(store.presentation_observations[-1]['context'],'during_dialogue')
        self.assertIsNone(store.presentation_observations[-1]['actor_id'])
        self.assertNotIn('setcell',AurigaRenderer().render(store.sessions[0]))
        store.apply(packet(0xb5,struct.pack('<I',42)))
        store.apply(event)
        self.assertEqual(store.presentation_observations[-1]['context'],'input_wait')
        store.apply(packet(0x192,b'bad'))
        self.assertEqual(store.issue_count,1)
        self.assertIn((0,'flow'),store.active)

    def test_cell_window_requires_exact_target_map_and_observed_scene(self):
        from copy import deepcopy
        from tests.support.event_trials import observation
        from reconstruction.event_trials import compare_event_trials
        from reconstruction.event_timer_export import build_timer_candidate
        def cell(when, **changes):
            return observation(when,kind='mapcell',actor_id=None,target_observed=False,
                entity_kind='unresolved',npc={},fields=dict(map_name='test.gat',x=100,y=200,cell_type=1),
                map_context=dict(map_name='test.gat',map_generation=1),**changes)
        rows=[observation(0),cell(1),observation(10),cell(11)]
        before=deepcopy(rows)
        report=compare_event_trials(rows,[0,2],window_ms=2000)
        self.assertEqual([len(t['events']) for t in report['trials']],[2,2])
        self.assertEqual(rows,before)
        code=build_timer_candidate(report,0,[100,1100],confirmed=True)['auriga']
        self.assertTrue(any(line.lstrip().startswith('//') and 'mapcell観測' in line
                            and 'test.gat' in line and 'x=100' in line and 'cell_type=1' in line
                            for line in code.splitlines()))
        self.assertFalse(any(line.strip().startswith('setcell ') for line in code.splitlines()))
        for replacement in (dict(fields=dict(map_name='other.gat',x=100,y=200,cell_type=1)),
                            dict(map_context=None),dict(flow_id='other'),dict(capture_session=1),
                            dict(context='input_wait'),dict(context='close_wait'),
                            dict(map_context=dict(map_name='test.gat',map_generation=2))):
            changed=deepcopy(rows)
            changed[1].update(replacement)
            result=compare_event_trials(changed,[0,2],window_ms=2000)
            self.assertEqual(len(result['trials'][0]['events']),1)
            self.assertEqual(result['status'],'observed_difference')

    def test_cell_retention_obeys_existing_capacity(self):
        store=DialogueStore()
        store.max_presentations=1
        store.apply(self.cell())
        store.apply(self.cell(2))
        self.assertEqual(len(store.presentation_observations),1)
        self.assertEqual(store.presentation_dropped,1)
        self.assertFalse(store.sessions)
