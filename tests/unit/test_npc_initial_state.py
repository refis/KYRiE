import struct
import unittest
from copy import deepcopy
from dataclasses import asdict, replace

from reconstruction.world import WorldStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.npc_bundle import build_npc_bundle
from tests.support.world import actor_packet, map_packet, packet
from tests.support.branches import conversation
from tests.unit.test_actor_identity import connection


def actor(options, endpoint=None):
    event = actor_packet(connection=endpoint or connection())
    raw = bytearray(event.raw)
    struct.pack_into('<I', raw, 19, options)
    return replace(event, raw=bytes(raw))


class NpcInitialStateTests(unittest.TestCase):
    def test_first_server_state_survives_updates_visibility_loss_and_reconnect_but_not_capture_boundary(self):
        world = WorldStore()
        first = connection()
        world.apply(map_packet(connection=first))
        world.apply(actor(2, first))
        initial_evidence = deepcopy(world.records()[0].initial_state_evidence)
        world.apply(packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 0, 0), connection=first))
        self.assertEqual(world.records()[0].options, 0)
        world.apply(packet(0x80, struct.pack('<IB', 42, 0), connection=first))
        world.apply(actor(4, first))
        second = connection(client_port=50001)
        world.apply(map_packet(connection=second))
        world.apply(actor(0, second))
        self.assertTrue(all(item.initial_options == 2 and item.initial_state_evidence == initial_evidence for item in world.records()))
        different = connection(port=5122)
        world.apply(actor(4, different))
        self.assertEqual(world.find_current(actor(4, different), 0, 42).initial_options, 4)
        world.apply(actor(0, first), session=1)
        self.assertEqual(world.find_current(actor(0, first), 1, 42).initial_options, 0)

    def test_initial_state_controls_single_merged_and_bundle_declarations(self):
        # type 6 uses script[(HIDDEN/CLOAKED)]; CLOAKED must not become script2.
        for initial, expected in ((0, '\tscript\t'), (2, '\tscript(HIDDEN)\t'), (4, '\tscript(CLOAKED)\t'),
                                  (0x12, '\tscript(HIDDEN)\t')):
            world = WorldStore()
            world.apply(map_packet(connection=connection()))
            world.apply(actor(initial))
            world.apply(actor(0))
            npc = asdict(world.records()[0])
            first, second = conversation(), conversation(identifier=2)
            first.npc, second.npc = deepcopy(npc), deepcopy(npc)
            before = deepcopy(npc)
            renderer = AurigaRenderer()
            self.assertIn(expected, renderer.render_npc_file(first))
            group = build_merged([('one', first), ('two', second)])['groups'][0]
            self.assertIn(expected, renderer.render_npc_file(first, group))
            for merge in (False, True):
                report = build_npc_bundle([npc], [first, second], merge=merge)
                self.assertIn(expected, report['auriga'])
                self.assertEqual(report['review_only_count'], 0)
            self.assertEqual(npc, before)

    def test_walking_npc_type_uses_script2_with_visibility_modifiers(self):
        for options, expected in ((0, '\tscript2\t'), (2, '\tscript2(HIDDEN)\t'), (4, '\tscript2(CLOAKED)\t')):
            world = WorldStore()
            world.apply(map_packet(connection=connection()))
            event = actor_packet(actor_type=12, connection=connection())
            raw = bytearray(event.raw)
            struct.pack_into('<I', raw, 19, options)
            world.apply(replace(event, raw=bytes(raw)))
            npc = asdict(world.records()[0])
            item = conversation()
            item.npc = deepcopy(npc)
            self.assertEqual(npc['actor_type'], 12)
            self.assertIn(expected, AurigaRenderer().render_npc_file(item))

    def test_initial_state_conflicts_and_combined_flags_do_not_silently_choose_active_definition(self):
        first, second = conversation(), conversation(identifier=2)
        first.npc.update(initial_options=2)
        second.npc.update(initial_options=4)
        group = build_merged([('one', first), ('two', second)])['groups'][0]
        with self.assertRaises(ValueError):
            AurigaRenderer().render_npc_file(first, group)
        report = build_npc_bundle([], [first, second], merge=True)
        self.assertEqual(report['review_only_count'], 1)
        self.assertTrue(all(not line.strip() or line.startswith('//') for line in report['auriga'].splitlines()))
        first.npc['initial_options'] = 6
        report = build_npc_bundle([], [first])
        self.assertFalse(report['entries'])
        self.assertEqual(report['excluded'][0]['kind'], 'npc_initial_state')
