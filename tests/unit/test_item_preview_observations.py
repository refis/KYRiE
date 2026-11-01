from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.decoder import ObservationError
from tests.support.dialogue import packet


def item_preview(index_raw=5, pid=0xab9):
    length = 47 if pid == 0xab9 else 48
    body = bytearray(length - 2)
    struct.pack_into('<H', body, 0, index_raw)
    return packet(pid, bytes(body))


class ItemPreviewObservationTests(unittest.TestCase):
    def test_item_preview_observes_index_without_npc_assignment_or_getitem(self):
        store = DialogueStore()
        events = [item_preview(5),
                  packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                  item_preview(7, pid=0xb13),
                  packet(0xb6, struct.pack('<I', 42)),
                  item_preview(9)]
        for event in events:
            store.apply(event)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows],
                         ['outside_dialogue', 'during_dialogue', 'close_wait'])
        self.assertTrue(all(row['kind'] == 'item_preview' and row['actor_id'] is None
                            and not row['target_observed'] and row['npc'] == {}
                            for row in rows))
        self.assertEqual([row['fields']['index'] for row in rows], [3, 5, 7])
        self.assertEqual([row['packet_id'] for row in rows], [0xab9, 0xb13, 0xab9])
        self.assertEqual(len(store.sessions), 1)
        self.assertFalse(any(step['kind'] == 'item_preview' for step in store.sessions[0].steps))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertNotIn('getitem', code)
        self.assertNotIn('itempreview', code)
        self.assertEqual(decode_dialogue(item_preview(5)),
                         ('item_preview', None, {'index': 3}))
        self.assertEqual(decode_dialogue(item_preview(4, pid=0xb13)),
                         ('item_preview', None, {'index': 2}))
        good = item_preview()
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))
        with self.assertRaises(ObservationError):
            decode_dialogue(item_preview(1))  # raw 1 - 2 = -1
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))

    def test_presentation_context_keeps_player_notification_boundary(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='item_preview', packet_id=0xab9, actor_id=None,
                   context='during_dialogue', npc={}, fields={'index': 3})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'not_recorded')
        self.assertTrue(note['player_context_required'])
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
