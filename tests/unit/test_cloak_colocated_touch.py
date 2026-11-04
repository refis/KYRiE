from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.touch import colocated_touch_npcs, TOUCH_CLASSES
from reconstruction.event_timer_export import _validate_observation_fields
from tests.support.world import actor_packet, map_packet, packet
from tests.unit.test_actor_identity import connection


def npc(options, *, actor_id=42, name='Subject', class_id=10429, x=334, y=138, endpoint=None):
    event = actor_packet(actor_id=actor_id, name=name, connection=endpoint or connection(), x=x, y=y)
    raw = bytearray(event.raw)
    struct.pack_into('<I', raw, 19, options)
    struct.pack_into('<H', raw, 23, class_id)
    return replace(event, raw=bytes(raw))


class CloakColocatedTouchTests(unittest.TestCase):
    def test_outside_cloakoff_notes_same_cell_touch_class_companion(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        flow = connection()
        events = [map_packet(connection=flow),
                  npc(0, actor_id=3705, name='#ch1evt_01', class_id=139, endpoint=flow),
                  npc(4, actor_id=3706, name='調査地点#ch01_1', class_id=10429, endpoint=flow),
                  packet(0x229, struct.pack('<IHHIB', 3706, 0, 0, 0, 0), connection=flow)]
        for event in events:
            world.apply(event, packet_index=store.packet_ordinal)
            store.apply(event)
        rows = [row for row in store.presentation_observations if row['kind'] == 'visibility_action']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['fields']['commands'], ['cloakoffnpc'])
        companions = row['fields']['colocated_touch_npcs']
        self.assertEqual(len(companions), 1)
        self.assertEqual(companions[0]['name'], '#ch1evt_01')
        self.assertEqual(companions[0]['class_id'], 139)
        self.assertIn(companions[0]['class_id'], TOUCH_CLASSES)
        with self.assertRaises(ValueError):
            _validate_observation_fields(row)  # extra colocated field blocks timer adoption
        from gui.presentation_context import presentation_context
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertIn('#ch1evt_01', note['summary'])
        self.assertIn('未生成', note['summary'])
        self.assertEqual(row, before)

    def test_helper_requires_same_cell_map_generation_and_touch_class(self):
        world = WorldStore()
        flow = connection()
        world.apply(map_packet(connection=flow))
        world.apply(npc(0, actor_id=1, name='#ch1evt_01', class_id=139, endpoint=flow))
        world.apply(npc(4, actor_id=2, name='調査地点#ch01_1', class_id=10429, endpoint=flow))
        subject = world.find_current(npc(4, actor_id=2, endpoint=flow), 0, 2, kind='NPC')
        matches = colocated_touch_npcs(world, npc(4, actor_id=2, endpoint=flow), 0, subject)
        self.assertEqual([row['name'] for row in matches], ['#ch1evt_01'])
        world.apply(npc(0, actor_id=3, name='other', class_id=139, x=335, y=138, endpoint=flow))
        matches = colocated_touch_npcs(world, npc(4, actor_id=2, endpoint=flow), 0, subject)
        self.assertEqual([row['name'] for row in matches], ['#ch1evt_01'])
