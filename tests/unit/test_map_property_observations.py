from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.decoder import ObservationError
from tests.support.dialogue import packet


def map_property(kind=4, flags=None):
    if flags is None:
        return packet(0x1d6, struct.pack('<H', kind))
    return packet(0x99b, struct.pack('<HI', kind, flags))


class MapPropertyObservationTests(unittest.TestCase):
    def test_map_property_observes_without_npc_assignment_or_command(self):
        store = DialogueStore()
        events = [map_property(4),
                  packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                  map_property(7, flags=0xABC),
                  packet(0xb6, struct.pack('<I', 42)),
                  map_property(1)]
        for event in events:
            store.apply(event)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows],
                         ['outside_dialogue', 'during_dialogue', 'close_wait'])
        self.assertTrue(all(row['kind'] == 'map_property' and row['actor_id'] is None
                            and not row['target_observed'] and row['npc'] == {}
                            for row in rows))
        self.assertEqual([row['fields'] for row in rows],
                         [{'kind': 4}, {'kind': 7, 'flags': 0xABC}, {'kind': 1}])
        self.assertFalse(any(step['kind'] == 'map_property' for step in store.sessions[0].steps))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertNotIn('mapproperty', code.lower())
        self.assertEqual(decode_dialogue(map_property(4)),
                         ('map_property', None, {'kind': 4}))
        self.assertEqual(decode_dialogue(map_property(2, flags=9)),
                         ('map_property', None, {'kind': 2, 'flags': 9}))
        good = map_property()
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))

    def test_presentation_context_keeps_map_boundary(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='map_property', packet_id=0x1d6, actor_id=None,
                   context='during_dialogue', npc={}, fields={'kind': 4})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'map_property')
        self.assertTrue(note['player_context_required'])
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
