from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.event_timer_export import _validate_observation_fields
from tests.support.world import actor_packet, map_packet, packet
from tests.unit.test_actor_identity import connection


def actor(options, endpoint=None, actor_id=42, name='CloakNpc'):
    event = actor_packet(actor_id=actor_id, name=name, connection=endpoint or connection())
    raw = bytearray(event.raw)
    struct.pack_into('<I', raw, 19, options)
    return replace(event, raw=bytes(raw))


class CloakAppearanceVsInitialTests(unittest.TestCase):
    def test_respawn_options_vs_initial_cloak_are_observed_without_timer_adoption(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        flow = connection()
        events = [map_packet(connection=flow),
                  actor(4, flow),  # first sight cloaked → initial_options=4
                  packet(0x80, struct.pack('<IB', 42, 0), connection=flow),
                  actor(0, flow)]  # reappear uncloaked while initial stays 4
        for event in events:
            world.apply(event, packet_index=store.packet_ordinal)
            store.apply(event)
        rows = [row for row in store.presentation_observations if row['kind'] == 'visibility_action']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['context'], 'outside_dialogue')
        self.assertEqual(row['fields']['commands'], ['cloakoffnpc'])
        self.assertEqual(row['fields']['previous_options'], 4)
        self.assertEqual(row['fields']['options'], 0)
        self.assertEqual(row['fields']['basis'], 'appearance_vs_initial')
        self.assertFalse(store.sessions)
        with self.assertRaises(ValueError):
            _validate_observation_fields(row)
        from gui.presentation_context import presentation_context
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertIn('initial_options', note['summary'])
        self.assertIn('タイマー', note['summary'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)

    def test_first_cloaked_spawn_does_not_emit_appearance_vs_initial(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        flow = connection()
        for event in (map_packet(connection=flow), actor(4, flow)):
            world.apply(event, packet_index=store.packet_ordinal)
            store.apply(event)
        self.assertFalse(any(row['kind'] == 'visibility_action' for row in store.presentation_observations))
