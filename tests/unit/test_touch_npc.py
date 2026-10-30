import struct
import unittest
from dataclasses import replace

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.branches import build_merged
from reconstruction.npc_bundle import build_npc_bundle
from reconstruction.touch import context
from tests.support.world import map_packet, actor_packet, packet
from tests.support.dialogue import packet as dialogue_packet


class TouchNpcTests(unittest.TestCase):
    def scene(self, extra=False, class_id=45):
        world = WorldStore()
        dialogues = DialogueStore(world=world)
        def consume(event, values=None):
            event = replace(event, connection='server', flow_id='game')
            index = dialogues.packet_ordinal
            world.apply(event, packet_index=index)
            dialogues.apply(event, packet_index=index, player_observation=values)
        consume(map_packet('test.gat'))
        first=actor_packet(name='Touch', x=150, y=200)
        raw=bytearray(first.raw);struct.pack_into('<H',raw,23,class_id)
        consume(replace(first,raw=bytes(raw)))
        if extra:
            consume(actor_packet(actor_id=43, name='Other', x=151, y=200))
        return world, dialogues, consume

    def position(self, consume, x=149, y=200):
        consume(packet(0xffff), dict(event_kind='position', map_name='test.gat', x=x, y=y))

    def test_touch_dialogue_and_warp_merge_without_fabricated_click(self):
        world, dialogues, consume = self.scene()
        self.position(consume)
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'cannot pass\0'))
        consume(packet(0xb6, struct.pack('<I', 42)))
        consume(packet(0x146, struct.pack('<I', 42), direction='SEND'))
        self.position(consume)
        consume(map_packet('target.gat', timestamp=10))
        self.assertEqual(len(dialogues.sessions), 2)
        self.assertTrue(all(not item.observed_open for item in dialogues.sessions))
        merged = build_merged(('', item) for item in dialogues.sessions)
        self.assertEqual(len(merged['groups']), 1)
        bundle = build_npc_bundle(world.snapshot('NPC')['entities'], dialogues.sessions, merge=True)
        code = bundle['auriga']
        self.assertIn('45,1,1,{', code)
        self.assertIn('OnTouch:', code)
        self.assertIn('mes "cannot pass";', code)
        self.assertIn('warp "target.gat",100,120;', code)
        self.assertNotIn('\twarp\t', code)
        self.assertIn('\n    {\n', code)

    def test_only_warp_becomes_native_warp_including_instances(self):
        for target in ('target.gat', '1@target.gat'):
            with self.subTest(target=target):
                world, dialogues, consume = self.scene()
                self.position(consume)
                consume(map_packet(target))
                bundle = build_npc_bundle([], dialogues.sessions, merge=True)
                self.assertIn('\twarp\tTouch\t1,1,' + target + ',100,120', bundle['auriga'])
                self.assertNotIn('\tscript\t', bundle['auriga'])
                self.assertEqual(bundle['review_only_count'], 0)
                self.assertTrue(any(line.startswith('test.gat,') and '\twarp\t' in line for line in bundle['auriga'].splitlines()))

    def test_ambiguous_nearby_npcs_do_not_claim_a_warp(self):
        world, dialogues, consume = self.scene(extra=True)
        self.position(consume, x=150, y=201)
        consume(map_packet('target.gat'))
        self.assertFalse(dialogues.sessions)
        evidence = dialogues.snapshot()['touch_warp_inferences'][0]
        self.assertEqual(evidence['reason'], 'ambiguous_nearest_in_highest_priority_class')
        self.assertIsNone(evidence['selected_actor_id'])
        self.assertEqual(evidence['candidate_count'], 2)

    def test_missing_position_uses_three_by_three_for_actor_addressed_dialogue(self):
        world, dialogues, consume = self.scene()
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        consume(packet(0xb6, struct.pack('<I', 42)))
        report = build_npc_bundle([], dialogues.sessions, merge=True)
        self.assertIn('45,1,1,{', report['auriga'])
        self.assertEqual(dialogues.sessions[0].npc['touch']['range_basis'], 'default_3x3')
        self.assertEqual(context({'class_id':45, 'map_name':'test.gat', 'x':10, 'y':20},
                                 {'map_name':'other.gat','x':10,'y':20},0)['range_basis'], 'default_3x3')

    def test_empty_placement_is_single_line_without_body_or_end(self):
        world, dialogues, consume = self.scene()
        npc = world.snapshot('NPC')['entities'][0]
        npc.update(group_id=0, title='', metadata_evidence={})
        report = build_npc_bundle([npc], [])
        self.assertEqual(report['entries'][0]['auriga'], 'test.gat,150,200,3\tscript\tTouch\t45,{}\n')

    def test_old_map_visibility_is_not_reused_for_another_warp(self):
        world, dialogues, consume = self.scene()
        self.position(consume)
        consume(map_packet('test.gat', timestamp=10))
        self.assertEqual(len(dialogues.sessions), 1)
        self.position(consume)
        consume(map_packet('target.gat', timestamp=20))
        self.assertEqual(len(dialogues.sessions), 1)

    def test_empty_placement_preserves_initial_visibility(self):
        world, dialogues, consume = self.scene()
        for options, keyword in ((2, 'script(HIDDEN)'), (4, 'script2(CLOAKED)')):
            with self.subTest(options=options):
                npc = world.snapshot('NPC')['entities'][0]
                npc.update(initial_options=options, group_id=0, title='', metadata_evidence={})
                code = build_npc_bundle([npc], [])['entries'][0]['auriga']
                self.assertIn('\t' + keyword + '\tTouch\t45,{}', code)
                self.assertEqual(len(code.splitlines()), 1)

    def test_walk_endpoint_never_expands_touch_range_or_claims_arrival(self):
        npc = dict(class_id=45, map_name='test.gat', x=150, y=200)
        position = dict(map_name='test.gat', x=160, y=210,
                        position_basis='observed_walk_destination', packet_index=10)
        result = context(npc, position, 11)
        self.assertEqual((result['radius_x'], result['radius_y']), (1, 1))
        self.assertEqual(result['range_basis'], 'walk_minimum_3x3')
        self.assertEqual(result['player'], position)
        self.assertFalse(result['cause_confirmed'])
        result = context(npc, dict(map_name='test.gat', x=150, y=200), 12)
        self.assertEqual((result['radius_x'], result['radius_y']), (1, 1))

    def test_instance_native_warp_uses_base_names_without_instance_warning_or_functions(self):
        world, dialogues, consume = self.scene()
        self.position(consume)
        consume(map_packet('0k81@target.gat'))
        item = dialogues.sessions[0]
        item.npc.update(map_name='0k81@source.gat', name='Touch_0k8')
        item.termination['fields']['source_map_name'] = '0k81@source.gat'
        bundle = build_npc_bundle([], [item], merge=True)
        code = bundle['entries'][0]['auriga']
        self.assertTrue(code.endswith('1@source.gat,150,200,3\twarp\tTouch\t1,1,1@target.gat,100,120\n'))
        self.assertIn('接触範囲は暫定値', code)
        self.assertNotIn('getmdmapname', code)
        self.assertEqual(bundle['review_only_count'], 0)
        self.assertEqual(item.npc['name'], 'Touch_0k8')
        self.assertEqual(item.termination['fields']['map_name'], '0k81@target.gat')

    def test_class139_dialogue_anchors_contact_without_claiming_all_events_are_touch(self):
        world, dialogues, consume = self.scene(class_id=139)
        event = actor_packet(name='Event', x=150, y=200)
        raw = bytearray(event.raw)
        struct.pack_into('<H', raw, 23, 139)
        consume(replace(event, raw=bytes(raw)))
        self.position(consume)
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'event dialogue\0'))
        consume(packet(0xb6, struct.pack('<I', 42)))
        item = dialogues.sessions[0]
        self.assertEqual(item.npc['touch']['basis'], 'class139_contact_candidate')
        report = build_npc_bundle([], dialogues.sessions, merge=True)
        self.assertIn('139,1,1,{', report['auriga'])
        self.assertIn('OnTouch:', report['auriga'])
        self.assertFalse(item.observed_open)

    def test_current_hide_and_cloak_disambiguate_colocated_contact_candidates(self):
        for initial_options, current_options in ((0, 0), (0, 2), (0, 4), (0, 6), (2, 0), (4, 0)):
            with self.subTest(initial_options=initial_options, current_options=current_options):
                world, dialogues, consume = self.scene()
                event = actor_packet(actor_id=43, name='Event', x=150, y=200)
                raw = bytearray(event.raw)
                struct.pack_into('<H', raw, 23, 139)
                struct.pack_into('<I', raw, 19, initial_options)
                consume(replace(event, raw=bytes(raw)))
                consume(packet(0x229, struct.pack('<IHHIB', 43, 0, 0, current_options, 0)))
                self.position(consume)
                consume(map_packet('target.gat'))
                if current_options:
                    self.assertEqual(len(dialogues.sessions), 1)
                    self.assertEqual(dialogues.sessions[0].actor_id, 42)
                else:
                    self.assertEqual(len(dialogues.sessions), 1)
                    self.assertEqual(dialogues.sessions[0].actor_id, 43)

    def test_axis_evidence_overrides_borrowed_values_and_removes_provisional_note(self):
        from copy import deepcopy
        from reconstruction.touch import merge_contexts
        from reconstruction.auriga import AurigaRenderer
        from tests.support.branches import conversation
        npc = dict(class_id=45, map_name='test.gat', x=10, y=20)
        x_only = context(npc, dict(map_name='test.gat', x=13, y=20), 1)
        y_only = context(npc, dict(map_name='test.gat', x=10, y=22), 2)
        self.assertEqual((x_only['radius_x'], x_only['radius_y']), (3, 3))
        self.assertEqual(x_only['confirmed_axes'], dict(x=True, y=False))
        merged = merge_contexts([x_only, y_only])
        self.assertEqual((merged['radius_x'], merged['radius_y']), (3, 2))
        self.assertFalse(merged['range_provisional'])
        first = conversation()
        first.npc['touch'] = x_only
        second = deepcopy(first)
        second.id = 2
        second.npc['touch'] = y_only
        partial = build_npc_bundle([], [first], merge=True)
        self.assertIn('45,3,3,{', partial['auriga'])
        self.assertIn('接触範囲は暫定値', partial['auriga'])
        for use_merge in (False, True):
            report = build_npc_bundle([], [first, second], merge=use_merge)
            self.assertIn('45,3,2,{', report['auriga'])
            self.assertNotIn('接触範囲は暫定値', report['auriga'])
        group = build_merged(('', item) for item in (first, second))['groups'][0]
        self.assertIn('45,3,2,{', AurigaRenderer().render_npc_file(first, group))
        self.assertEqual(first.npc['touch'], x_only)

    def test_empty_npcs_are_one_line_for_every_class(self):
        world, dialogues, consume = self.scene()
        for class_id in (45, 139, 100, 1000):
            with self.subTest(class_id=class_id):
                npc = world.snapshot('NPC')['entities'][0]
                npc['initial_display']['class_id']=class_id
                npc.update(class_id=class_id, group_id=0, title='', metadata_evidence={})
                code = build_npc_bundle([npc], [])['entries'][0]['auriga']
                self.assertEqual(len(code.splitlines()), 1)
                self.assertTrue(code.endswith(str(class_id) + ',{}\n'))

    def test_contact_priority_and_maximum_fifteen_cell_radius(self):
        for class_id in (139, 111, 844, 45, 100):
            for distance in (15, 16):
                with self.subTest(class_id=class_id, distance=distance):
                    world, dialogues, consume = self.scene(class_id=class_id)
                    # Replace the original actor with the tested class and a higher-position candidate.
                    event = actor_packet(actor_id=42, name='Preferred', x=150, y=200)
                    raw = bytearray(event.raw)
                    struct.pack_into('<H', raw, 23, class_id)
                    consume(replace(event, raw=bytes(raw)))
                    self.position(consume, x=150 + distance, y=200)
                    consume(map_packet('target.gat'))
                    self.assertEqual(bool(dialogues.sessions), distance == 15)
        # A lower-priority but closer class45 must not override class139.
        world, dialogues, consume = self.scene()
        event = actor_packet(actor_id=43, name='Preferred', x=160, y=200)
        raw = bytearray(event.raw)
        struct.pack_into('<H', raw, 23, 139)
        consume(replace(event, raw=bytes(raw)))
        self.position(consume, x=150, y=200)
        consume(map_packet('target.gat'))
        self.assertEqual(dialogues.sessions[0].actor_id, 43)

    def test_same_priority_uses_unique_nearest_without_claiming_cause(self):
        world, dialogues, consume = self.scene(extra=True)
        self.position(consume, x=150, y=200)
        consume(map_packet('target.gat'))
        self.assertEqual(dialogues.sessions[0].actor_id, 42)
        evidence = dialogues.snapshot()['touch_warp_inferences'][0]
        self.assertEqual(evidence['candidate_count'], 2)
        self.assertEqual(evidence['nearest_count'], 1)
        self.assertEqual(evidence['nearest_distance'], 0)
        self.assertFalse(evidence['cause_confirmed'])
