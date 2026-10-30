from tests.support.branches import conversation
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from reconstruction.auriga import AurigaRenderer, DEFAULT_DIALOGUE_PROFILE
from reconstruction.branches import build_merged
from storage.session_log import SessionLog
from tools.merge_dialogues import merge
from tests.support.world import actor_packet, map_packet
from tests.support.dialogue import packet





class BranchTests(unittest.TestCase):
    def test_parallel_presentations_compare_without_changing_reply_or_generated_order(self):
        from reconstruction.dialogue import DialogueStore
        from tests.support.branches import NPC
        for prompt_pid, reply_pid, prompt_body, reply_body in (
                (0xb7, 0xb8, b'one:two:\0', b'\x01'),
                (0xb5, 0xb9, b'', b''),
                (0x142, 0x143, b'', struct.pack('<i', 7)),
                (0x1d4, 0x1d5, b'', b'text\0')):
            with self.subTest(prompt=prompt_pid):
                trials = []
                for attempt in (1, 2):
                    store = DialogueStore()
                    records = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=0),
                               packet(prompt_pid, struct.pack('<I', 42) + prompt_body, timestamp=1)]
                    if attempt == 1:
                        records.append(packet(0xc0, struct.pack('<IB', 42, 8), timestamp=2))
                    records.extend([packet(reply_pid, struct.pack('<I', 42) + reply_body, 'SEND', timestamp=3),
                                    packet(0xb4, struct.pack('<I', 42) + b'continued\0', timestamp=4),
                                    packet(0xb6, struct.pack('<I', 42), timestamp=5)])
                    for record in records:
                        store.apply(record)
                    item = store.sessions[0]
                    item.npc = dict(NPC)
                    trials.append((str(attempt), item))
                group = build_merged(trials)['groups'][0]
                self.assertEqual(group['presentation_check']['conflicts'], 1)
                code = AurigaRenderer().render_merged(group)
                self.assertIn('mes "continued";', code)
                self.assertNotIn('emotion 8;', code)
                self.assertFalse(group['conflicts'])
                events = [variant['events'] for variant in group['presentation_check']['comparisons'][0]['variants']]
                self.assertTrue(any(event and event[0]['track'] == 'input_wait' for event in events))
                trials[0][1].parallel_presentations[0]['timestamp'] = 99
                rejected = build_merged(trials)
                self.assertEqual(rejected['excluded'][0]['reason'], 'reply_or_layout_conflict')

    def test_repeated_presentations_detect_presence_order_values_and_keep_evidence(self):
        def trial(events, identifier=1, choice=1):
            item = conversation(identifier=identifier, choice=choice)
            # Append presentation observations after the reply; keep reply links intact.
            for kind, fields in events:
                step = copy.deepcopy(item.steps[-1])
                step.update(kind=kind, fields=fields)
                item.steps.insert(-1, step)
            return item
        emotion = ('emotion', dict(value=3))
        effect = ('effect', dict(value=99))
        sound = ('sound', dict(sound='test.wav', mode=1, interval=250))
        for first, second in (([emotion], []), ([emotion], [('emotion', dict(value=4))]),
                              ([effect], [('effect', dict(value=100))]),
                              ([sound], [('sound', dict(sound='other.wav', mode=1, interval=250))]),
                              ([sound], [('sound', dict(sound='test.wav', mode=2, interval=250))]),
                              ([sound], [('sound', dict(sound='test.wav', mode=1, interval=500))]),
                              ([emotion], [emotion, emotion]),
                              ([emotion, sound], [sound, emotion])):
            with self.subTest(first=first, second=second):
                a, b = trial(first), trial(second, 2)
                report = build_merged([('a', a), ('b', b), ('a', a)])
                group = report['groups'][0]
                check = group['presentation_check']
                self.assertEqual(check['conflicts'], 1)
                row = check['comparisons'][0]
                self.assertEqual((row['status'], row['trials']), ('conflicting_observations', 2))
                self.assertFalse(row['cause_confirmed'])
                refs = [o for variant in row['variants'] for o in variant['observations']]
                self.assertEqual({r['source_ref'] for r in refs}, {'a', 'b'})
                self.assertTrue(any(r['event_evidence'] for r in refs))
                self.assertIn('要確認', AurigaRenderer().render_merged(group))
                self.assertIn('要確認', AurigaRenderer().render(a, presentation_check=check))
        for observations, status in (([('a', trial([emotion]))], 'insufficient_observations'),
                                      ([('a', trial([emotion])), ('b', trial([emotion], 2))], 'consistent_observations'),
                                      ([('a', trial([emotion])), ('b', trial([], 2, choice=2))], 'insufficient_observations')):
            check = build_merged(observations)['groups'][0]['presentation_check']
            self.assertEqual(check['conflicts'], 0)
            self.assertEqual(check['comparisons'][0]['status'], status)
            self.assertFalse(check['cause_confirmed'])
        first, second = trial([emotion]), trial([emotion], 2)
        moved = second.steps.pop(-2)
        second.steps.insert(-2, moved)  # Before the final message, rather than after it.
        check = build_merged([('a', first), ('b', second)])['groups'][0]['presentation_check']
        self.assertEqual(check['conflicts'], 1)

    def test_two_selected_paths_merge_with_unobserved_third_and_evidence(self):
        first = conversation()
        second = conversation(2, 'two result', actor=99)
        report = build_merged([('a', first), ('b', second)])
        self.assertEqual(len(report['groups']), 1)
        group = report['groups'][0]
        self.assertEqual(group['menus'][0]['observed'], [1, 2])
        self.assertEqual(group['menus'][0]['unobserved'], [3])
        code = AurigaRenderer().render_merged(group)
        self.assertEqual(code.count('mes "hello";'), 1)
        self.assertIn('mes "one result";', code)
        self.assertIn('mes "two result";', code)
        self.assertEqual(code.count('未観測の分岐'), 1)
        self.assertFalse(group['server_conditions_restored'])
        sources = {ref['source_ref'] for node in group['nodes'] for ref in node['evidence']}
        self.assertEqual(sources, {'a', 'b'})
        self.assertTrue(all('timeline' in ref for ref in group['contributions']))
        node = next(node for node in group['nodes'] if node['kind'] == 'mes')
        node['fields']['text'] = 'modified candidate'
        self.assertEqual(first.steps[1]['fields']['text'], 'hello')

    def test_divergence_without_different_choice_is_preserved_in_indented_blocks(self):
        report = build_merged([('a', conversation(answer='hidden A')), ('b', conversation(answer='hidden B'))])
        group = report['groups'][0]
        self.assertEqual(len(group['conflicts']), 1)
        code = AurigaRenderer().render_merged(group)
        self.assertIn('異なる観測結果', code)
        self.assertIn('hidden A', code)
        self.assertIn('hidden B', code)
        self.assertIn('        {\n            mes "hidden A";', code)
        self.assertIn('        {\n            mes "hidden B";', code)
        self.assertNotIn('if (', code)
        self.assertIn('mes "hello";', code)

    def test_nested_menus_and_escaping_do_not_invent_labels_from_text(self):
        report = build_merged([('a', conversation(nested=True, answer='quoted "text"\\')),
                               ('b', conversation(2, 'other branch'))])
        code = AurigaRenderer().render_merged(report['groups'][0])
        self.assertEqual(code.count('menu '), 2)
        self.assertIn('mes "quoted \\"text\\"\\\\";', code)
        self.assertEqual(code.count('switch (@menu)'), 2)
        self.assertNotIn('GPM_', code)
        self.assertNotIn('sleep', code)
        self.assertNotIn('OnTimer', code)

    def test_input_suffix_continues_with_observation_comments_and_no_inferred_condition(self):
        report = build_merged([('a', conversation(input_prompt=True, answer='input A')),
                               ('b', conversation(input_prompt=True, answer='input B'))])
        code = AurigaRenderer().render_merged(report['groups'][0])
        self.assertIn("input '@gpa_number;", code)
        self.assertIn('// 入力数: 1', code)
        self.assertIn('input A', code)
        self.assertIn('input B', code)
        self.assertNotIn('if (', code)
        sources = [row['conversation'] for row in report['groups'][0]['contributions']]
        self.assertTrue(any(step['fields'].get('text') == 'input A' for item in sources for step in item['steps']))

    def test_identified_placements_stay_separate_and_unknown_map_is_capture_local(self):
        first, second = conversation(), conversation(2, identifier=2)
        second.npc['x'] = 11
        self.assertEqual(len(build_merged([('a', first), ('b', second)])['groups']), 2)
        first.npc['map_name'] = None
        second.npc = dict(first.npc)
        third, fourth = copy.deepcopy(first), copy.deepcopy(first)
        third.id, fourth.id = 3, 4
        fourth.npc['appearance'] = 2
        report = build_merged([('a', first), ('a', second), ('b', third), ('a', fourth)])
        self.assertEqual(len(report['groups']), 3)
        merged = next(group for group in report['groups'] if len(group['contributions']) == 2)
        self.assertEqual(merged['npc']['scope'], 'capture_entity')
        self.assertEqual(merged['npc']['source_ref'], 'a')

    def test_incomplete_unidentified_assumed_and_broken_replies_are_excluded(self):
        for problem in ('identity', 'status', 'assumed', 'reply', 'choice', 'open'):
            with self.subTest(problem=problem):
                item = conversation()
                if problem == 'identity':
                    item.npc = {}
                elif problem == 'status':
                    item.status = 'observing'
                elif problem == 'assumed':
                    item.steps[0]['connection'] = 'flow [ASSUMED=1]'
                elif problem == 'reply':
                    item.steps[3]['reply_to'] = 0
                elif problem == 'choice':
                    item.steps[3]['fields']['value'] = 0
                else:
                    item.observed_open = False
                report = build_merged([('a', item)])
                self.assertEqual(report['groups'], [])
                self.assertEqual(len(report['excluded']), 1)

    def test_input_order_deduplication_and_limits_are_deterministic(self):
        first, second = conversation(), conversation(2)
        a = build_merged([('a', first), ('b', second)])
        b = build_merged([('b', second), ('a', first), ('a', first)])
        self.assertEqual(a, b)
        self.assertEqual(build_merged([('a', first)], max_nodes=1)['groups'], [])
        self.assertEqual(build_merged([('a', first)], max_semantic_bytes=1)['groups'], [])
        self.assertEqual(build_merged([('a', first)], max_total_steps=1)['groups'], [])
        self.assertTrue(build_merged([('a', first), ('b', second)], max_observations=1)['input_capacity_reached'])

    def test_render_expansion_limits_do_not_return_partial_candidates(self):
        group = build_merged([('a', conversation())])['groups'][0]
        with self.assertRaises(ValueError):
            AurigaRenderer().render_merged(group, max_output_chars=20)
        with self.assertRaises(ValueError):
            AurigaRenderer().render_merged(group, max_pending_actions=1)
        result = AurigaRenderer().render_groups([group], max_output_chars=20)
        self.assertEqual(result['auriga'], [None])
        self.assertEqual(result['generation_errors'][0]['group_id'], group['id'])

    def test_menu_layout_changes_are_separate_blocks_not_reordered_choices(self):
        first, second = conversation(), conversation(2)
        second.steps[2]['fields']['options'].reverse()
        report = build_merged([('a', first), ('b', second)])
        code = AurigaRenderer().render_merged(report['groups'][0])
        self.assertIn('異なる観測結果', code)
        self.assertIn('{\n    menu "one:two:three",-;', code)
        self.assertIn('{\n    menu "three:two:one",-;', code)

    def test_old_profiles_remain_usable_and_custom_merged_templates_are_external(self):
        group = build_merged([('a', conversation())])['groups'][0]
        with tempfile.TemporaryDirectory() as folder:
            document = json.loads(DEFAULT_DIALOGUE_PROFILE.read_text(encoding='utf-8'))
            for key in list(document):
                if key.startswith('merge'):
                    del document[key]
            path = Path(folder) / 'profile.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertIn('mes "hello";', AurigaRenderer(path).render_merged(group))
            document['merged_header'] = '// custom {id}: {observations}'
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertIn('// custom 1: 1', AurigaRenderer(path).render_merged(group))
            document['merged_header'] = '{npc_name.__class__}'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(ValueError):
                AurigaRenderer(path)

    def test_map_boundary_keeps_termination_evidence_without_inventing_warp(self):
        item = conversation()
        item.steps.pop()  # No close was observed.
        item.status = 'map_changed'
        item.termination = dict(packet_index=99, packet_id=0x91, timestamp=2, connection='half', direction='RECV')
        report = build_merged([('a', item)])
        group = report['groups'][0]
        boundary = next(node for node in group['nodes'] if node['kind'] == 'boundary')
        self.assertEqual(boundary['evidence'][0]['packet_index'], 99)
        code = AurigaRenderer().render_merged(group)
        self.assertIn('マップ移動を観測', code)
        self.assertNotIn('warp ', code)

    def test_cutin_state_is_copied_into_each_menu_branch(self):
        first, second = conversation(), conversation(2, identifier=2)
        # Insert a cutin before the branch result, then repair source step links.
        for item in (first, second):
            cutin = copy.deepcopy(item.steps[1])
            cutin.update(kind='cutin', fields=dict(image='portrait', position=0))
            item.steps.insert(2, cutin)
            item.steps[3]['reply'] = 4
            item.steps[4]['reply_to'] = 3
        hide = copy.deepcopy(second.steps[2])
        hide['fields']['position'] = 255
        second.steps.insert(-1, hide)
        group = build_merged([('a', first), ('b', second)])['groups'][0]
        code = AurigaRenderer().render_merged(group)
        self.assertEqual(code.count('close2;'), 0)
        self.assertEqual(sum(line.strip() == 'close;' for line in code.splitlines()), 2)

    def test_cross_log_replay_merges_only_identified_npc_placements(self):
        definitions = {0x91: 22, 0x9ff: -1, 0x90: 7, 0xb4: -1, 0xb7: -1, 0xb8: 7, 0xb6: 6, 0x19b: 10}
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for attempt, choice in enumerate((1, 1, 2)):
                log = SessionLog(folder, definitions, record_payload=True)
                log.write('capture_format', transport='tcp_segments', capture_send=True)
                incoming, outgoing = ('server', 1, 'client', 2), ('client', 2, 'server', 1)
                initial = map_packet().raw + actor_packet().raw
                opened = packet(0x90, struct.pack('<IB', 42, 1), 'SEND').raw
                prompt = (packet(0xb4, struct.pack('<I', 42) + b'hello\0').raw
                          + packet(0xb7, struct.pack('<I', 42) + b'one:two:\0').raw)
                answer = packet(0xb8, struct.pack('<IB', 42, choice), 'SEND').raw
                result = (packet(0xb4, struct.pack('<I', 42) + f'result-{choice}\0'.encode()).raw
                          + packet(0x19b, struct.pack('<II', 42, 99 + attempt)).raw
                          + packet(0xb6, struct.pack('<I', 42)).raw)
                for endpoints, seq, flags, data, time, direction in (
                    (outgoing, 10, 2, b'', 0, 'SEND'), (incoming, 30, 18, b'', 0, 'RECV'),
                    (incoming, 31, 16, initial, 1, 'RECV'), (outgoing, 11, 16, opened, 2, 'SEND'),
                    (incoming, 31 + len(initial), 16, prompt, 3, 'RECV'),
                    (outgoing, 11 + len(opened), 16, answer, 4, 'SEND'),
                    (incoming, 31 + len(initial) + len(prompt), 16, result, 5, 'RECV')):
                    log.write('tcp_segment', endpoints=endpoints, sequence=seq, flags=flags, data=data,
                              timestamp=time, direction=direction)
                log.close()
                paths.append(log.path)
            report = merge(paths + paths, definitions)
            self.assertEqual(len(report['sources']), 3)
            self.assertEqual(len(report['groups']), 1)
            self.assertEqual(len(report['groups'][0]['contributions']), 3)
            self.assertEqual(report['groups'][0]['presentation_check']['conflicts'], 1)
            self.assertIn('要確認', report['auriga'][0])
            self.assertEqual(report['groups'][0]['npc']['scope'], 'identified_placement')
            self.assertIn('result-1', report['auriga'][0])
            self.assertIn('result-2', report['auriga'][0])


if __name__ == '__main__':
    unittest.main()

