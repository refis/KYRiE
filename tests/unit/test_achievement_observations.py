from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.decoder import ObservationError
from tests.support.dialogue import packet


def achievement(achievement_id=501):
    body = bytearray(64)
    struct.pack_into('<I', body, 14, achievement_id)  # raw offset 16 = body offset 14 after pid
    return packet(0xa24, bytes(body))


class AchievementObservationTests(unittest.TestCase):
    def test_achievement_observes_id_without_npc_assignment_or_command(self):
        store = DialogueStore()
        events = [achievement(12),
                  packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                  achievement(99),
                  packet(0xb6, struct.pack('<I', 42)),
                  achievement(7)]
        for event in events:
            store.apply(event)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows],
                         ['outside_dialogue', 'during_dialogue', 'close_wait'])
        self.assertTrue(all(row['kind'] == 'achievement' and row['actor_id'] is None
                            and not row['target_observed'] and row['npc'] == {}
                            for row in rows))
        self.assertEqual([row['fields']['achievement_id'] for row in rows], [12, 99, 7])
        self.assertEqual(len(store.sessions), 1)
        self.assertFalse(any(step['kind'] == 'achievement' for step in store.sessions[0].steps))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertNotIn('achievement ', code)
        self.assertEqual(decode_dialogue(achievement(501)),
                         ('achievement', None, {'achievement_id': 501}))
        good = achievement()
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))

    def test_presentation_context_keeps_player_notification_boundary(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='achievement', packet_id=0xa24, actor_id=None,
                   context='during_dialogue', npc={}, fields={'achievement_id': 3})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'not_recorded')
        self.assertTrue(note['player_context_required'])
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
