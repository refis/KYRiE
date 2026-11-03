from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.decoder import ObservationError
from tests.support.dialogue import packet


def navigation_active(nav_type=0, set_type=0x65, hide=1, map_name=b'ygg_edge', x=253, y=246, spr=1002):
    body = bytearray(25)
    body[0] = nav_type
    body[1] = set_type
    body[2] = hide
    name = map_name.split(b'\0', 1)[0][:15]
    body[3:3 + len(name)] = name
    struct.pack_into('<hhh', body, 19, x, y, spr)
    return packet(0x8e2, bytes(body))


class NavigationActiveObservationTests(unittest.TestCase):
    def test_navigation_active_observes_official_layout_without_npc_assignment(self):
        store = DialogueStore()
        events = [navigation_active(),
                  packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                  navigation_active(nav_type=1, set_type=0, hide=0, map_name=b'prontera', x=0, y=0, spr=0),
                  packet(0xb6, struct.pack('<I', 42)),
                  navigation_active(map_name=b'pay_fild01', x=10, y=20, spr=0)]
        for event in events:
            store.apply(event)
        rows = store.presentation_observations
        self.assertEqual([row['context'] for row in rows],
                         ['outside_dialogue', 'during_dialogue', 'close_wait'])
        self.assertTrue(all(row['kind'] == 'navigation_active' and row['actor_id'] is None
                            and not row['target_observed'] and row['npc'] == {}
                            for row in rows))
        self.assertEqual(rows[0]['fields'],
                         dict(type=0, set_type=0x65, hide=1, map_name='ygg_edge', x=253, y=246, spr_index=1002))
        self.assertEqual(rows[1]['fields']['map_name'], 'prontera')
        self.assertEqual(rows[1]['fields']['type'], 1)
        self.assertEqual(len(store.sessions), 1)
        self.assertFalse(any(step['kind'] == 'navigation_active' for step in store.sessions[0].steps))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertNotIn('navigateto', code)
        self.assertNotIn('@navigation', code)
        self.assertEqual(
            decode_dialogue(navigation_active()),
            ('navigation_active', None,
             dict(type=0, set_type=0x65, hide=1, map_name='ygg_edge', x=253, y=246, spr_index=1002)))
        good = navigation_active()
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))

    def test_capture_sample_matches_official_offsets(self):
        raw = bytes.fromhex('e2080065017967675f656467650000000000000000fd00f600ea03')
        event = replace(navigation_active(), raw=raw)
        kind, actor, fields = decode_dialogue(event)
        self.assertEqual(kind, 'navigation_active')
        self.assertIsNone(actor)
        self.assertEqual(fields, dict(type=0, set_type=0x65, hide=1, map_name='ygg_edge',
                                      x=253, y=246, spr_index=1002))

    def test_presentation_context_keeps_player_notification_boundary(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='navigation_active', packet_id=0x8e2, actor_id=None,
                   context='during_dialogue', npc={},
                   fields=dict(type=0, set_type=101, hide=1, map_name='ygg_edge', x=253, y=246, spr_index=1002))
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'not_recorded')
        self.assertTrue(note['player_context_required'])
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
