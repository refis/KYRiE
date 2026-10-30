import struct
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from tests.support.dialogue import packet
from tests.support.branches import NPC


class ClassChangeTests(unittest.TestCase):
    def change(self, actor=42, extra=b''):
        return packet(0x1b0, struct.pack('<IBI', actor, 1, 1005) + extra)

    def test_same_actor_generates_setnpcdisplay_and_conflicts_across_repeats(self):
        trials = []
        for changed in (False, True):
            store = DialogueStore()
            store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
            store.apply(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
            if changed:
                store.apply(self.change())
            store.apply(packet(0xb6, struct.pack('<I', 42)))
            item = store.sessions[0]
            item.npc = dict(NPC)
            trials.append((str(changed), item))
        code = AurigaRenderer().render(trials[1][1])
        self.assertIn('setnpcdisplay "案内人",1005;', code)
        merged = build_merged(trials)
        self.assertEqual(merged['groups'][0]['presentation_check']['conflicts'], 1)

    def test_input_wait_other_actor_and_malformed_are_isolated(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0x142, struct.pack('<I', 42)))
        store.apply(self.change())
        store.apply(self.change(actor=99))
        store.apply(packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(item.steps[2]['reply_to'], 1)
        self.assertEqual([row['context'] for row in store.presentation_observations],
                         ['input_wait', 'outside_dialogue'])
        self.assertNotIn('class=1005', AurigaRenderer().render(item))
        store.apply(self.change(extra=b'extra'))
        self.assertEqual(store.issue_count, 1)
