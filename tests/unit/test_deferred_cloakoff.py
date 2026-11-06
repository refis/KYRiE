"""Deferred unobserved 0x0229 cloakoff → named cloakoffnpc after spawn."""
import struct
import unittest
from copy import deepcopy
from dataclasses import replace

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.conversation_actions import validate_actions
from gui.presentation_context import presentation_context
from tests.support.world import map_packet, actor_packet, packet
from tests.support.dialogue import packet as dialogue_packet


class DeferredCloakoffTests(unittest.TestCase):
    def opened(self):
        world = WorldStore()
        store = DialogueStore(world=world)

        def consume(event):
            event = replace(event, timestamp=float(store.packet_ordinal + 1))
            world.apply(event, packet_index=store.packet_ordinal)
            store.apply(event)

        consume(map_packet('prontera.gat'))
        consume(packet(0x283, struct.pack('<I', 777)))
        event = actor_packet(actor_id=42, name='Owner')
        raw = bytearray(event.raw)
        struct.pack_into('<I', raw, 19, 0)
        consume(replace(event, raw=bytes(raw)))
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'hello\0', flow=None, connection='flow-a'))
        return store, consume

    def test_unobserved_cloakoff_resolves_name_with_actor_id_comment(self):
        store, consume = self.opened()
        # Out-of-sight unobserved NPC: first 0x0229 with clear cloak bit during dialogue.
        consume(packet(0x229, struct.pack('<IHHIB', 99, 0, 0, 0, 0)))
        self.assertTrue(store.pending_visibility)
        pending_rows = [row for row in store.presentation_observations
                        if row['kind'] == 'visibility_action'
                        and row['fields'].get('basis') == 'deferred_unobserved']
        self.assertEqual(len(pending_rows), 1)
        self.assertEqual(pending_rows[0]['fields']['commands'], ['cloakoffnpc'])
        self.assertIsNone(pending_rows[0]['fields']['target'])
        note = presentation_context(pending_rows[0])
        self.assertIn('未観測', note['short'])

        # Later observation supplies the name; script gets cloakoffnpc "Name"; // actor_id.
        later = actor_packet(actor_id=99, name='HiddenGuest')
        raw = bytearray(later.raw)
        struct.pack_into('<I', raw, 19, 0)
        consume(replace(later, raw=bytes(raw)))
        self.assertFalse(store.pending_visibility)
        item = store.sessions[0]
        resolved = [row for row in item.actions
                    if row['kind'] == 'visibility_action'
                    and row['fields'].get('basis') == 'deferred_name_resolved']
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]['fields']['commands'], ['cloakoffnpc'])
        self.assertEqual(resolved[0]['fields']['target']['name'], 'HiddenGuest')
        self.assertEqual(resolved[0]['fields']['target']['actor_id'], 99)
        validate_actions(item)
        code = AurigaRenderer().render(item)
        self.assertIn('cloakoffnpc "HiddenGuest"; // 99', code)

    def test_map_change_drops_pending_unobserved_cloakoff(self):
        store, consume = self.opened()
        consume(packet(0x229, struct.pack('<IHHIB', 99, 0, 0, 0, 0)))
        self.assertTrue(store.pending_visibility)
        consume(map_packet('geffen.gat'))
        self.assertFalse(store.pending_visibility)
        self.assertFalse(store.unobserved_visibility_options)
        later = actor_packet(actor_id=99, name='HiddenGuest')
        raw = bytearray(later.raw)
        struct.pack_into('<I', raw, 19, 0)
        before = deepcopy(store.sessions[0].actions)
        consume(replace(later, raw=bytes(raw)))
        self.assertEqual(store.sessions[0].actions, before)


if __name__ == '__main__':
    unittest.main()
