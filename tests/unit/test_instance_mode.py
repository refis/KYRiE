import struct
import json
import unittest
from copy import deepcopy
from dataclasses import replace

from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.dialogue import DialogueStore
from reconstruction.world import WorldStore
from reconstruction.event_trials import compare_event_trials
from reconstruction.event_timer_export import build_timer_candidate
from reconstruction.shop_export import ShopRenderer
from tests.support.branches import NPC
from tests.support.dialogue import packet
from tests.support.display import variable
from tests.support.world import actor_packet, map_packet, packet as world_packet
from tests.unit.test_shop_export import observe_shop


class InstanceModeTests(unittest.TestCase):
    def test_instance_projection_removes_only_complete_matching_runtime_suffix(self):
        from reconstruction.instance_names import map_name, npc_name, projection
        for token in ('0k8', 'Ab9'):
            raw_map = token + '1@xm_d.gat'
            self.assertEqual(map_name(raw_map), '1@xm_d.gat')
            self.assertEqual(npc_name('#fac1wp_' + token, raw_map), '#fac1wp')
            for ending in ('_', '_' + token[:1], '_' + token[:2], '_zzz', '_other'):
                raw_name = '#original' + ending
                self.assertEqual(npc_name(raw_name, raw_map), raw_name)
            self.assertEqual(projection(dict(map_name=raw_map, name='#original_' + token[:2]))['npc_suffix_status'],
                             'ambiguous_partial')
        self.assertEqual(map_name('1@xm_d.gat'), '1@xm_d.gat')
        self.assertEqual(map_name('prontera.gat'), 'prontera.gat')
        truncated = 'あ' * 10 + '_0k'
        self.assertEqual(len(truncated.encode('cp932')), 23)
        self.assertEqual(npc_name(truncated, '0k81@xm_d.gat'), truncated)
        self.assertEqual(npc_name('#name_0k8', '1@xm_d.gat'), '#name_0k8')

    def test_instance_runtime_names_project_to_declarations_and_warp_calls_without_mutating_evidence(self):
        from reconstruction.npc_bundle import build_npc_bundle
        from tests.support.branches import conversation
        item = conversation()
        item.npc.update(map_name='0k81@xm_d.gat', name='#fac1wp_0k8')
        before = deepcopy(item)
        code = AurigaRenderer().render_npc_file(item)
        self.assertIn('1@xm_d.gat,10,20,0\tscript\t#fac1wp\t45,{', code)
        bundle = build_npc_bundle([], [item], merge=True)
        self.assertEqual(bundle['entries'][0]['npc']['name'], '#fac1wp_0k8')
        self.assertEqual(bundle['entries'][0]['rendered_names']['npc_name'], '#fac1wp')
        self.assertEqual(item, before)
        from parser.display import DisplayProfile, ReceiveDisplay, DEFAULT_PROFILE
        display = ReceiveDisplay(DisplayProfile(json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))))
        display.decode(map_packet('0k81@xm_d.gat'))
        event = display.decode(map_packet('0k81@xm_d.gat'))
        self.assertIn('getmdmapname("1@xm_d.gat")', event.text)
        self.assertEqual(event.fields['map'], '0k81@xm_d.gat')

    def test_display_tracks_instance_transitions_preserves_raw_names_and_legacy_profiles(self):
        from parser.display import DisplayProfile, ReceiveDisplay, DEFAULT_PROFILE, ProfileError
        document = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        display = ReceiveDisplay(DisplayProfile(document))
        self.assertIn('warp "prontera.gat",', display.decode(map_packet('prontera.gat')).text)
        entry = display.decode(map_packet('1@toy.gat'))
        self.assertTrue(entry.text.startswith('// warp "1@toy.gat"'))
        self.assertIn('mdenter', entry.text)
        internal = display.decode(map_packet('1@toy.gat'))
        self.assertIn('warp getmdmapname("1@toy.gat"),', internal.text)
        self.assertEqual(internal.fields['map'], '1@toy.gat')
        self.assertIn('warp "prontera.gat",', display.decode(map_packet('prontera.gat')).text)
        self.assertTrue(display.decode(map_packet('1@toy.gat')).text.startswith('// warp'))
        for key in ('instance_warp', 'instance_entry_warp', 'instance_map_reference'):
            document.pop(key)
        legacy = ReceiveDisplay(DisplayProfile(document))
        self.assertTrue(legacy.decode(map_packet('1@toy.gat')).text.startswith('warp "1@toy.gat"'))
        with self.assertRaises(ProfileError):
            DisplayProfile(dict(document, instance_warp='warp {map};'))

    def test_warp_uses_instance_reference_or_comments_entry_and_preserves_sources(self):
        for source, destination, expected in (
                ('1@toy.gat', '1@toy.gat', 'warp getmdmapname("1@toy.gat"),10,20;'),
                ('1@toy.gat', '2@toy.gat', 'warp getmdmapname("2@toy.gat"),10,20;'),
                ('prontera.gat', '1@toy.gat', '// warp "1@toy.gat",10,20;'),
                (None, '1@toy.gat', '// warp "1@toy.gat",10,20;'),
                ('1@toy.gat', 'prontera.gat', 'warp "prontera.gat",10,20;'),
                ('prontera.gat', 'geffen.gat', 'warp "geffen.gat",10,20;')):
            store = DialogueStore()
            for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                          packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                          packet(0xb6, struct.pack('<I', 42)),
                          packet(0x146, struct.pack('<I', 42), 'SEND')):
                store.apply(event)
            item = store.sessions[0]
            item.npc = dict(NPC, map_name=source)
            store.apply(packet(0x91, destination.encode().ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
            before = deepcopy(item)
            code = AurigaRenderer().render(item)
            self.assertIn(expected, code)
            self.assertEqual(item.steps[-1]['fields']['source_map_name'], source)
            self.assertEqual(item, before)
            if source:
                merged = build_merged([('log', item)])
                self.assertIn(expected, AurigaRenderer().render_merged(merged['groups'][0]))

    def test_instance_callshop_wraps_name_reference_but_keeps_declaration_literal(self):
        record, item = observe_shop(True)
        item.npc['map_name'] = '1@toy.gat'
        record['npc']['map_name'] = '1@toy.gat'
        before = deepcopy(item)
        text = ShopRenderer().render(record, 'callshop', item_ids_confirmed=True, conversation=item)
        self.assertIn('callshop getmdnpcname("GPA_S', text)
        self.assertIn('1@toy.gat,10,20,0\tscript\t案内人', text)
        self.assertIn('-\tshop\tGPA_S', text)
        self.assertEqual(item, before)

    def test_instance_announcements_join_timer_trials_without_actor_ownership_and_do_not_cross_maps(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        def consume(event):
            world.apply(event)
            store.apply(event)
        def announce(text, timestamp):
            return replace(variable(0x1c3, struct.pack('<IHHHH', 1, 400, 12, 0, 0) + text + b'\0'),
                           connection='flow-a', flow_id='', timestamp=timestamp)
        consume(map_packet('1@toy.gat', timestamp=0))
        consume(actor_packet(timestamp=.1))
        consume(world_packet(0xc0, struct.pack('<IB', 42, 7), timestamp=1))
        consume(announce(b'first', 2))
        consume(world_packet(0xc0, struct.pack('<IB', 42, 7), timestamp=11))
        consume(announce(b'other-user-notice', 12))
        consume(map_packet('prontera.gat', timestamp=13))
        consume(announce(b'other-map', 14))
        rows = store.presentation_observations
        self.assertEqual(store.issue_count, 0)
        self.assertTrue(rows[1]['instance_mode'])
        self.assertFalse(rows[-1]['instance_mode'])
        self.assertIsNone(rows[1]['actor_id'])
        self.assertFalse(rows[1]['target_observed'])
        report = compare_event_trials(rows, [0, 2], window_ms=5000)
        self.assertEqual(report['status'], 'observed_difference')
        self.assertEqual([len(trial['events']) for trial in report['trials']], [2, 2])
        candidate = build_timer_candidate(report, 0, [100, 1100], confirmed=True)
        self.assertIn('announce "first",0x9,', candidate['auriga'])
        self.assertNotIn('other-map', candidate['auriga'])
        self.assertFalse(candidate['cause_confirmed'])
