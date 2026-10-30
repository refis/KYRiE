import struct
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from tests.support.dialogue import packet, viewpoint_event
from tests.support.branches import NPC


class ViewpointTests(unittest.TestCase):
    def opened(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        return store

    def test_supported_markers_generate_in_order_and_preserve_raw_color(self):
        store = self.opened()
        for kind in (1, 2):
            store.apply(viewpoint_event(kind=kind))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(item.steps[2]['fields']['color'], 0xff123456)
        code = AurigaRenderer().render(item)
        self.assertIn('viewpoint 1,100,200,7,0x123456;', code)
        self.assertIn('viewpoint 2,100,200,7,0x123456;', code)
        self.assertLess(code.index('viewpoint 1'), code.index('viewpoint 2'))
        self.assertLess(code.index('viewpoint 2'), code.index('close;'))

    def test_unknown_values_remain_comments_and_repeat_changes_are_flagged(self):
        trials = []
        for kind, x in ((1, 100), (99, 0xffffffff)):
            store = self.opened()
            store.apply(viewpoint_event(kind=kind, x=x))
            store.apply(packet(0xb6, struct.pack('<I', 42)))
            item = store.sessions[0]
            item.npc = dict(NPC)
            trials.append((str(kind), item))
        code = AurigaRenderer().render(trials[1][1])
        self.assertIn('type=99', code)
        self.assertFalse(any(line.startswith('viewpoint ') for line in code.splitlines()))
        self.assertEqual(build_merged(trials)['groups'][0]['presentation_check']['conflicts'], 1)

    def test_input_wait_and_other_actor_are_separate_and_malformed_is_reported(self):
        store = self.opened()
        store.apply(packet(0x142, struct.pack('<I', 42)))
        store.apply(viewpoint_event())
        store.apply(viewpoint_event(actor=99))
        store.apply(packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        self.assertEqual(store.sessions[0].steps[3]['reply_to'], 2)
        self.assertEqual([row['context'] for row in store.presentation_observations],
                         ['input_wait', 'outside_dialogue'])
        self.assertNotIn('viewpoint ', AurigaRenderer().render(store.sessions[0]))
        store.apply(packet(0x144, bytes(22)))
        self.assertEqual(store.issue_count, 1)

    def test_display_context_preserves_target_and_never_confirms_cause(self):
        from copy import deepcopy
        from gui.presentation_context import presentation_context
        row = dict(kind='viewpoint', packet_id=324, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'}, fields={'value': 9})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'marker_npc')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertEqual(note['player_context_required'], True)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
