import struct
import unittest
from dataclasses import replace

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.branches import build_merged
from reconstruction.npc_bundle import build_npc_bundle
from reconstruction.touch import (context, compare_trials, format_trial_comparison, merge_contexts,
                                  membership_transition)
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
        self.assertIn('45,1,1,{/*', code)
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
        self.assertIn('45,1,1,{/*', report['auriga'])
        self.assertEqual(dialogues.sessions[0].npc['touch']['range_basis'], 'default_3x3')
        self.assertEqual(context({'class_id':45, 'map_name':'test.gat', 'x':10, 'y':20},
                                 {'map_name':'other.gat','x':10,'y':20},0)['range_basis'], 'default_3x3')

    def test_empty_placement_is_single_line_without_body_or_end(self):
        world, dialogues, consume = self.scene()
        npc = world.snapshot('NPC')['entities'][0]
        npc.update(group_id=0, title='', metadata_evidence={})
        report = build_npc_bundle([npc], [])
        self.assertEqual(report['entries'][0]['auriga'], 'test.gat,150,200,3\tscript\tTouch\t45,{/* 42 */}\n')

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
        for options, keyword in ((2, 'script(HIDDEN)'), (4, 'script(CLOAKED)')):
            with self.subTest(options=options):
                npc = world.snapshot('NPC')['entities'][0]
                npc.update(initial_options=options, group_id=0, title='', metadata_evidence={})
                code = build_npc_bundle([npc], [])['entries'][0]['auriga']
                self.assertIn('\t' + keyword + '\tTouch\t45,{/* 42 */}', code)
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
        self.assertIn('139,1,1,{/*', report['auriga'])
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
                self.assertTrue(code.endswith(',{/* %s */}\n' % npc['actor_id']))
                self.assertIn('\t%d,' % class_id, code.split('\tscript\t', 1)[1])

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

    def test_two_walk_destination_trials_compare_without_expanding_range(self):
        world = WorldStore()
        dialogues = DialogueStore(world=world)
        def consume(event, values=None, timestamp=1.0):
            event = replace(event, connection='server', flow_id='game', timestamp=timestamp)
            index = dialogues.packet_ordinal
            world.apply(event, packet_index=index)
            dialogues.apply(event, packet_index=index, player_observation=values)
        def place(timestamp):
            consume(map_packet('map_a.gat', timestamp=timestamp), timestamp=timestamp)
            first = actor_packet(name='Gate', x=172, y=163)
            raw = bytearray(first.raw)
            struct.pack_into('<H', raw, 23, 45)
            consume(replace(first, raw=bytes(raw)), timestamp=timestamp)
        place(1.0)
        consume(packet(0x85, bytes(3), direction='SEND'), timestamp=2.0)
        consume(packet(0xffff), dict(event_kind='walk', map_name='map_a.gat', x=168, y=163,
                                     destination_x=170, destination_y=163), timestamp=2.0)
        consume(map_packet('map_b.gat', timestamp=3.0), timestamp=3.0)
        place(4.0)
        consume(packet(0x85, bytes(3), direction='SEND'), timestamp=5.0)
        consume(packet(0xffff), dict(event_kind='walk', map_name='map_a.gat', x=172, y=161,
                                     destination_x=172, destination_y=165), timestamp=5.0)
        consume(map_packet('map_b.gat', timestamp=6.0), timestamp=6.0)
        self.assertEqual(len(dialogues.sessions), 2)
        offsets = [item.npc['touch']['signed_offsets'] for item in dialogues.sessions]
        self.assertEqual(offsets, [{'dx': -2, 'dy': 0}, {'dx': 0, 'dy': 2}])
        for item in dialogues.sessions:
            touch = item.npc['touch']
            self.assertEqual((touch['radius_x'], touch['radius_y']), (1, 1))
            self.assertEqual(touch['range_basis'], 'walk_minimum_3x3')
            self.assertTrue(touch['range_provisional'])
            self.assertFalse(touch['cause_confirmed'])
            self.assertFalse(any(touch['confirmed_axes'].values()))
            self.assertIsInstance(touch['player']['walk_send_packet_index'], int)
        comparisons = dialogues.snapshot()['touch_trial_comparisons']
        self.assertEqual(len(comparisons), 1)
        rows = comparisons[0]['trials']
        self.assertEqual(len(rows), 2)
        self.assertEqual([(row['signed_dx'], row['signed_dy'], row['position_basis']) for row in rows],
                         [(-2, 0, 'observed_walk_destination'), (0, 2, 'observed_walk_destination')])
        self.assertTrue(all(row['walk_send_packet_index'] is not None for row in rows))
        self.assertTrue(all(row['walk_recv_packet_index'] is not None for row in rows))
        self.assertTrue(all(row['transfer_packet_index'] is not None for row in rows))
        self.assertTrue(all(row['candidate_count'] == 1 for row in rows))
        self.assertIn('暫定半径1は既定の仮値', comparisons[0]['caption'])
        self.assertNotIn('半径2', comparisons[0]['caption'])
        merged = build_merged(('', item) for item in dialogues.sessions)
        group = merged['groups'][0]
        self.assertEqual(len(group['touch_trial_comparison']), 2)
        self.assertIn('walk_minimum_3x3', group['touch_trial_caption'])
        bundle = build_npc_bundle([], dialogues.sessions, merge=True,
                                  touch_inferences=list(dialogues.touch_warp_inferences))
        touch = bundle['entries'][0]['npc']['touch']
        self.assertEqual((touch['radius_x'], touch['radius_y']), (1, 1))
        self.assertTrue(touch['range_provisional'])
        self.assertIn('1,1,map_b.gat', bundle['auriga'])
        self.assertNotIn('2,2,', bundle['auriga'])
        self.assertEqual(len(bundle['entries'][0]['touch_trial_comparison']), 2)
        merged_touch = merge_contexts([item.npc['touch'] for item in dialogues.sessions])
        self.assertEqual((merged_touch['radius_x'], merged_touch['radius_y']), (1, 1))
        self.assertTrue(merged_touch['range_provisional'])

    def test_compare_trials_keeps_provenance_without_inventing_ontouch_range(self):
        npc = dict(class_id=45, map_name='map_a.gat', x=172, y=163, flow_id='game',
                   capture_session=0, map_generation=1, actor_id=42)
        first = context(npc, dict(map_name='map_a.gat', x=170, y=163,
                                  position_basis='observed_walk_destination', packet_index=3,
                                  walk_send_packet_index=2), 4)
        second = context(npc, dict(map_name='map_a.gat', x=172, y=165,
                                   position_basis='observed_walk_destination', packet_index=8,
                                   walk_send_packet_index=7), 9)
        rows = compare_trials([
            dict(source_ref='a.jsonl', capture_session=0, conversation_id=1, flow_id='game',
                 npc=dict(npc, touch=first), termination=dict(packet_index=4, packet_id=0x91)),
            dict(source_ref='a.jsonl', capture_session=0, conversation_id=2, flow_id='game',
                 npc=dict(npc, touch=second, map_generation=3),
                 termination=dict(packet_index=9, packet_id=0x91)),
        ], inferences=[
            dict(capture_session=0, flow_id='game', packet_index=4, candidate_count=1,
                 nearest_count=1, reason='unique_nearest_in_highest_priority_class', selected_actor_id=42),
            dict(capture_session=0, flow_id='game', packet_index=9, candidate_count=1,
                 nearest_count=1, reason='unique_nearest_in_highest_priority_class', selected_actor_id=42),
        ])
        self.assertEqual([(row['signed_dx'], row['signed_dy']) for row in rows], [(-2, 0), (0, 2)])
        self.assertTrue(all(row['range_basis'] == 'walk_minimum_3x3' for row in rows))
        self.assertTrue(all(row['range_provisional'] for row in rows))
        caption = format_trial_comparison(rows)
        self.assertIn('歩行SEND#2', caption)
        self.assertIn('転送#9', caption)
        self.assertIn('候補1', caption)

    def test_observed_offset_confirms_both_axes_at_plus_two(self):
        npc = dict(class_id=45, map_name='test.gat', x=150, y=200)
        # Enter (+2,+2): both axes get independent nonzero evidence.
        result = context(npc, dict(map_name='test.gat', x=152, y=202,
                                   position_basis='observed_position'), 5)
        self.assertEqual((result['radius_x'], result['radius_y']), (2, 2))
        self.assertEqual(result['confirmed_axes'], dict(x=True, y=True))
        self.assertFalse(result['range_provisional'])
        self.assertEqual(result['range_basis'], 'observed_minimum')
        self.assertEqual(result['signed_offsets'], dict(dx=2, dy=2))

    def test_coverage_reentry_only_on_leave_and_return(self):
        entered, left = membership_transition({42}, {42})
        self.assertEqual(entered, frozenset())
        self.assertEqual(left, frozenset())
        entered, left = membership_transition({42}, frozenset())
        self.assertEqual(entered, frozenset())
        self.assertEqual(left, frozenset({42}))
        entered, left = membership_transition(frozenset(), {42})
        self.assertEqual(entered, frozenset({42}))
        self.assertEqual(left, frozenset())

    def test_unique_range_entry_cloak_opens_touch_frame_not_timer_presentation(self):
        world, dialogues, consume = self.scene()
        # Approach from outside the search window, then step onto (+2,+0).
        self.position(consume, x=130, y=200)
        self.position(consume, x=152, y=200)
        consume(packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 4, 0)))
        self.assertEqual(len(dialogues.sessions), 1)
        item = dialogues.sessions[0]
        self.assertTrue(item.npc.get('touch'))
        self.assertEqual(item.npc['touch'].get('frame_basis'), 'range_entry')
        self.assertEqual(item.npc['touch']['confirmed_axes'], dict(x=True, y=False))
        self.assertEqual(len(item.actions), 1)
        self.assertEqual(item.actions[0]['kind'], 'visibility_action')
        self.assertEqual(item.actions[0]['fields']['basis'], 'touch_range_entry')
        self.assertFalse(any(row['kind'] == 'visibility_action'
                             for row in dialogues.presentation_observations))

    def test_colocated_same_cell_entry_stays_ambiguous_for_warp(self):
        world, dialogues, consume = self.scene(class_id=139)
        event = actor_packet(actor_id=43, name='Peer', x=150, y=200)
        raw = bytearray(event.raw)
        struct.pack_into('<H', raw, 23, 139)
        consume(replace(event, raw=bytes(raw)))
        self.position(consume, x=150, y=201)
        consume(map_packet('target.gat'))
        evidence = dialogues.snapshot()['touch_warp_inferences'][0]
        self.assertEqual(evidence['reason'], 'simultaneous_colocated_touch_candidates')
        self.assertTrue(evidence['colocated_same_cell'])
        self.assertIsNone(evidence['selected_actor_id'])
        self.assertFalse(dialogues.sessions)

    def test_moving_inside_range_does_not_reopen_touch_frame(self):
        world, dialogues, consume = self.scene()
        self.position(consume, x=130, y=200)
        self.position(consume, x=152, y=200)
        consume(packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 4, 0)))
        self.assertEqual(len(dialogues.sessions), 1)
        # Stay inside / move to another covered cell: no second entry association.
        dialogues.active.clear()
        self.position(consume, x=151, y=200)
        consume(packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 0, 0)))
        self.assertEqual(len(dialogues.sessions), 1)
        self.assertTrue(any(row['kind'] == 'visibility_action'
                            for row in dialogues.presentation_observations))
