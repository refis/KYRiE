import struct
import unittest

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from tests.support.dialogue import packet
from tests.support.branches import NPC


class ProgressBarTests(unittest.TestCase):
    def bar(self, actor=42, seconds=3):
        return packet(0x9d1, struct.pack('<III', actor, 0xabcdef, seconds))

    def opened(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        return store

    def test_targeted_notifications_preserve_fields_and_repeat_conflicts_without_wait_commands(self):
        trials = []
        for seconds in (3, 5):
            store = self.opened()
            store.apply(self.bar(seconds=seconds))
            store.apply(packet(0xb6, struct.pack('<I', 42)))
            item = store.sessions[0]
            item.npc = dict(NPC)
            self.assertEqual(item.steps[2]['fields'], {'color': 0xabcdef, 'seconds': seconds})
            code = AurigaRenderer().render(item)
            self.assertIn(f'秒数={seconds}', code)
            self.assertFalse(any(row.startswith(('progressbar ', 'sleep ', 'sleep2 ', 'OnTimer'))
                                 for row in code.splitlines()))
            trials.append((str(seconds), item))
        self.assertEqual(build_merged(trials)['groups'][0]['presentation_check']['conflicts'], 1)

    def test_unidentified_and_other_actor_notifications_do_not_change_prompt_links(self):
        store = self.opened()
        store.apply(packet(0x142, struct.pack('<I', 42)))
        store.apply(packet(0x2f0, struct.pack('<II', 0x123456, 7)))
        store.apply(self.bar())
        store.apply(self.bar(actor=99))
        store.apply(packet(0x143, struct.pack('<Ii', 42, 10), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(item.steps[3]['reply_to'], 2)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows], ['input_wait', 'outside_dialogue'])
        self.assertEqual(item.actions[0]['kind'], 'progress_action')
        self.assertIn('progressbar 7,0x123456;', AurigaRenderer().render(item))
        self.assertNotIn('秒数=', AurigaRenderer().render(item))

    def test_malformed_layouts_are_reported_and_send_is_not_decoded(self):
        for pid, raw in ((0x2f0, b'bad'), (0x9d1, bytes(13))):
            with self.subTest(pid=pid):
                store = self.opened()
                store.apply(packet(pid, raw))
                self.assertEqual(store.issue_count, 1)
                self.assertFalse(store.presentation_observations)
        self.assertIsNone(decode_dialogue(packet(0x2f0, bytes(8), 'SEND')))
