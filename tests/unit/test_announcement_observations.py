import struct
import unittest
from dataclasses import replace

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from tests.support.dialogue import packet
from tests.support.display import variable


class AnnouncementObservationTests(unittest.TestCase):
    def test_dialogue_merging_detects_announcement_presence_text_and_style_conflicts(self):
        from reconstruction.branches import build_merged
        from tests.support.branches import NPC
        for waiting in (False, True):
            for change in ('missing', 'text', 'style'):
                trials = []
                for attempt in (0, 1):
                    store = DialogueStore()
                    events = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                              packet(0xb4, struct.pack('<I', 42) + b'hello\0')]
                    if waiting:
                        events.append(packet(0xb5, struct.pack('<I', 42)))
                    if not (attempt and change == 'missing'):
                        style = struct.pack('<IHHHH', 99 if attempt and change == 'style' else 1, 400, 12, 0, 0)
                        notice = b'other\0' if attempt and change == 'text' else b'notice\0'
                        events.append(replace(variable(0x1c3, style + notice), connection='half', flow_id='flow', timestamp=1))
                    if waiting:
                        events.append(packet(0xb9, struct.pack('<I', 42), 'SEND'))
                    events.append(packet(0xb6, struct.pack('<I', 42)))
                    for event in events:
                        store.apply(event)
                    item = store.sessions[0]
                    item.npc = dict(NPC)
                    trials.append((str(attempt), item))
                report = build_merged(trials)
                self.assertFalse(report['excluded'])
                group = report['groups'][0]
                self.assertEqual(group['presentation_check']['conflicts'], 1)
                code = AurigaRenderer().render_merged(group)
                self.assertIn('要確認', code)
                if not waiting:
                    self.assertIn('announce "notice",0x9,', code)
                    self.assertIn('{\n', code)

    def test_timer_window_includes_unassigned_announcement_and_manual_adoption_preserves_evidence(self):
        from copy import deepcopy
        from tests.support.event_trials import observation
        from reconstruction.event_trials import compare_event_trials
        from reconstruction.event_timer_export import build_timer_candidate, validate_timer_candidate
        def announce(time, text='notice', **changes):
            return observation(time, kind='announcement', actor_id=None, target_observed=False,
                entity_kind='unresolved', npc={}, fields=dict(text=text, broadcast_prefix=None), **changes)
        rows = [observation(0), announce(1), announce(1.2, 'wrong-flow', flow_id='other'),
                observation(10), announce(11, 'changed'), observation(20)]
        before = deepcopy(rows)
        report = compare_event_trials(rows, [0, 3, 5], window_ms=2000)
        self.assertEqual(report['status'], 'observed_difference')
        self.assertEqual([len(trial['events']) for trial in report['trials']], [2, 2, 1])
        followup = report['trials'][0]['events'][1]
        self.assertEqual(followup['association_basis'], 'selected_timer_window_same_flow')
        self.assertIsNone(followup['observation']['actor_id'])
        self.assertFalse(followup['observation']['target_observed'])
        with self.assertRaises(ValueError):
            build_timer_candidate(report, 0, [100, 1100])
        saved = build_timer_candidate(report, 0, [100, 1100], confirmed=True)
        self.assertIn('announce "notice",0;', saved['auriga'])
        self.assertFalse(saved['cause_confirmed'])
        self.assertEqual(validate_timer_candidate(saved, report, 0), saved)
        self.assertEqual(rows, before)
        styled = deepcopy(report)
        styled['trials'][0]['events'][1]['observation']['fields'] = dict(
            text='quoted "text"\nline', color=0xff123456, font_type=400, font_size=12, font_align=0, font_y=0)
        styled_code = build_timer_candidate(styled, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('announce "quoted \\"text\\"\\nline",0x9,', styled_code)
        changed = deepcopy(report)
        changed['trials'][0]['events'][1]['observation']['flow_id'] = 'other'
        with self.assertRaises(ValueError):
            build_timer_candidate(changed, 0, [100, 1100], confirmed=True)

    def test_broadcast_and_styled_notifications_remain_unassigned_during_input_and_close(self):
        store = DialogueStore()
        broadcast = variable(0x9a, b'blue' + '告知'.encode('cp932') + b'\0')
        styled = variable(0x1c3, struct.pack('<IHHHH', 0xff123456, 400, 12, 1, 2) + b'notice\0')
        def same_flow(event):
            return replace(event, connection='half', flow_id='flow')
        for event in (same_flow(broadcast), packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0x142, struct.pack('<I', 42)), same_flow(styled),
                      packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'),
                      packet(0xb6, struct.pack('<I', 42)), same_flow(styled),
                      packet(0x146, struct.pack('<I', 42), 'SEND'), same_flow(styled)):
            store.apply(event)
        self.assertEqual(store.issue_count, 0)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows],
                         ['outside_dialogue', 'input_wait', 'close_wait', 'outside_dialogue'])
        self.assertTrue(all(row['actor_id'] is None and not row['target_observed'] and row['npc'] == {} for row in rows))
        self.assertEqual(rows[0]['fields'], dict(text='告知', broadcast_prefix='blue'))
        self.assertEqual(rows[1]['fields']['color'], 0xff123456)
        self.assertEqual(rows[1]['fields']['font_y'], 2)
        self.assertEqual(store.sessions[0].steps[2]['reply_to'], 1)
        self.assertNotIn('announce', AurigaRenderer().render(store.sessions[0]))
        self.assertNotIn('close2;', AurigaRenderer().render(store.sessions[0]))
        for prefix in (b'ssss', b'tool', b''):
            fields = decode_dialogue(variable(0x9a, prefix + b'notice\0'))[2]
            self.assertEqual(fields['text'], 'notice')
        self.assertEqual(decode_dialogue(variable(0x40c, styled.raw[4:]))[2], rows[1]['fields'])

    def test_invalid_layout_encoding_and_direction_do_not_create_observations(self):
        good = variable(0x1c3, struct.pack('<IHHHH', 1, 400, 12, 0, 0) + b'ok\0')
        for event in (replace(good, raw=good.raw[:-1]), variable(0x1c3, b'too short\0'),
                      variable(0x9a, b'missing terminator'), variable(0x9a, b'\x81\0')):
            store = DialogueStore()
            store.apply(event)
            self.assertEqual(store.issue_count, 1)
            self.assertFalse(store.presentation_observations)
            self.assertNotIn('missing terminator', str(store.issues))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        limited = DialogueStore(max_presentations=1)
        limited.apply(good)
        limited.apply(good)
        self.assertEqual(len(limited.presentation_observations), 1)
        self.assertEqual(limited.presentation_dropped, 1)
