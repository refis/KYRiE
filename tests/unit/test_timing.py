import copy
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer, DEFAULT_DIALOGUE_PROFILE
from reconstruction.timing import build_timeline, summarize_timings
from storage.session_log import SessionLog
from tools.analyze_dialogues import analyze
from tools.compare_dialogue_timing import compare
from tests.support.dialogue import packet


NPC = dict(map_name='test.gat', name='案内人', class_id=45, x=10, y=20)


def observed(gap=2, start=0, identity=True):
    store = DialogueStore()
    for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=start),
                  packet(0xb4, struct.pack('<I', 42) + b'one\0', timestamp=start + .05),
                  packet(0xb4, struct.pack('<I', 42) + b'two\0', timestamp=start + .05 + gap)):
        store.apply(event)
    item = store.sessions[0]
    if identity:
        item.npc = dict(NPC)
    return item


class TimingTests(unittest.TestCase):
    def test_separates_input_wait_and_response_from_autonomous_gap(self):
        store = DialogueStore()
        events = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=0),
                  packet(0xb4, struct.pack('<I', 42) + b'one\0', timestamp=.05),
                  packet(0xb5, struct.pack('<I', 42), timestamp=.1),
                  packet(0x1b3, b'image'.ljust(64, b'\0') + b'\0', timestamp=1),
                  packet(0xb9, struct.pack('<I', 42), 'SEND', timestamp=4.1),
                  packet(0xb4, struct.pack('<I', 42) + b'two\0', timestamp=4.2),
                  packet(0xb4, struct.pack('<I', 42) + b'three\0', timestamp=6.2),
                  packet(0xb6, struct.pack('<I', 42), timestamp=6.21),
                  packet(0x146, struct.pack('<I', 42), 'SEND', timestamp=9.3)]
        for event in events:
            store.apply(event)
        result = build_timeline(store.sessions[0])
        self.assertEqual(result['rows'][3]['interval'], 'during_input_wait')
        self.assertEqual(result['rows'][5]['interval'], 'response_latency')
        self.assertEqual([span['duration_ms'] for span in result['waits']], [4000, 3090])
        self.assertEqual([gap['duration_ms'] for gap in result['candidates']], [2000])
        self.assertEqual(result['candidates'][0]['from_packet_index'], 5)
        self.assertEqual(result['candidates'][0]['to_packet_index'], 6)
        self.assertFalse(result['server_timer_confirmed'])
        self.assertEqual(result['rows'][3]['track'], 'parallel_presentation')
        self.assertIsNone(result['rows'][3]['step_index'])
        code = AurigaRenderer().render(store.sessions[0])
        self.assertNotIn('cutin "image"', code)
        self.assertIn('mes "three";', code)

    def test_missing_response_remains_open_wait_even_at_map_boundary(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=0))
        store.apply(packet(0xb7, struct.pack('<I', 42) + b'a:b:\0', timestamp=1))
        store.apply(packet(0x91, bytes(20), timestamp=5), packet_index=99)
        result = build_timeline(store.sessions[0])
        self.assertEqual(result['waits'][0]['duration_ms'], None)
        self.assertFalse(result['waits'][0]['complete'])
        self.assertEqual(result['waits'][0]['observed_until_ms'], 4000)
        self.assertEqual(result['rows'][-1]['packet_index'], 99)
        self.assertEqual(result['rows'][-1]['kind'], 'map_changed')
        self.assertEqual(result['candidates'], [])

    def test_bad_time_partial_capture_and_ambiguous_reply_disqualify_candidates(self):
        for case in ('reverse', 'nan', 'inf', 'partial', 'issue', 'assumed', 'interrupted'):
            with self.subTest(case=case):
                item = observed()
                if case == 'reverse':
                    item.steps[-1]['timestamp'] = -1
                elif case in ('nan', 'inf'):
                    item.steps[-1]['timestamp'] = float(case)
                elif case == 'partial':
                    item.observed_open = False
                elif case == 'issue':
                    item.issues.append(dict(message='Mismatch'))
                elif case == 'assumed':
                    item.steps[0]['connection'] = 'flow [ASSUMED=1]'
                else:
                    item.status = 'interrupted'
                result = build_timeline(item)
                self.assertTrue(result['quality_flags'])
                self.assertFalse(result['candidates'])
                if case == 'assumed':
                    self.assertEqual(len(result['excluded_gaps']), 1)
                    self.assertIn('assumed_boundary', result['excluded_gaps'][0]['reasons'])

    def test_zero_and_same_timestamp_and_threshold(self):
        self.assertEqual(build_timeline(observed(0))['candidates'], [])
        self.assertEqual(build_timeline(observed(.099))['candidates'], [])
        self.assertEqual(len(build_timeline(observed(.1))['candidates']), 1)
        for threshold in (-1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                build_timeline(observed(), min_gap_ms=threshold)

    def test_generated_gap_is_only_an_external_template_comment(self):
        item = observed()
        renderer = AurigaRenderer()
        code = renderer.render(item)
        self.assertIn('観測時間差 2000.0 ms', code)
        self.assertNotIn('sleep', code)
        self.assertNotIn('OnTimer', code)
        with tempfile.TemporaryDirectory() as folder:
            profile = json.loads(DEFAULT_DIALOGUE_PROFILE.read_text(encoding='utf-8'))
            del profile['observed_gap']  # Existing custom profiles remain loadable.
            path = Path(folder) / 'profile.json'
            path.write_text(json.dumps(profile), encoding='utf-8')
            old_code = AurigaRenderer(path).render(item)
        commands = lambda text: [line for line in text.splitlines() if not line.startswith('//')]
        self.assertEqual(commands(code), commands(old_code))

    def test_repeat_statistics_deduplicate_and_do_not_merge_unknown_npc(self):
        timelines = [build_timeline(observed(gap, start), source_ref=f'log-{i}')
                     for i, (gap, start) in enumerate(((1.99, 0), (2, 100), (2.01, 200)))]
        result = summarize_timings(timelines + [copy.deepcopy(timelines[0])])
        group = result['groups'][0]
        self.assertEqual(group['count'], 3)
        self.assertEqual(group['median_ms'], 2000)
        self.assertEqual(group['spread_ms'], 20)
        self.assertEqual(group['status'], 'repeated_consistent')
        self.assertFalse(group['server_timer_confirmed'])
        unknown = build_timeline(observed(identity=False))
        self.assertEqual(summarize_timings([unknown])['unidentified_candidates'], 1)
        self.assertEqual(summarize_timings([unknown])['groups'], [])
        self.assertEqual(summarize_timings(timelines[:1])['groups'][0]['status'], 'insufficient_repeats')

    def test_paths_inputs_and_npc_placements_are_separate(self):
        first = observed()
        second = observed()
        second.steps[1]['fields']['text'] = 'different branch'
        third = observed()
        third.npc['x'] = 11
        result = summarize_timings([build_timeline(item, str(i)) for i, item in enumerate((first, second, third))])
        self.assertEqual(len(result['groups']), 3)
        variable = [build_timeline(observed(gap), str(i)) for i, gap in enumerate((1, 2, 3))]
        self.assertEqual(summarize_timings(variable)['groups'][0]['status'], 'repeated_variable')
        for kwargs in ({'minimum_repeats': 1}, {'absolute_tolerance_ms': -1}, {'relative_tolerance': math.nan}):
            with self.assertRaises(ValueError):
                summarize_timings([], **kwargs)

    def test_offline_replay_timelines_keep_source_and_deduplicate_same_path(self):
        definitions = {0x90: 7, 0xb4: -1}
        with tempfile.TemporaryDirectory() as folder:
            session = SessionLog(folder, definitions, record_payload=True)
            session.write('capture_format', transport='tcp_segments', capture_send=True)
            incoming = ('server', 1, 'client', 2)
            outgoing = ('client', 2, 'server', 1)
            for endpoints, sequence, flags, data, timestamp, direction in (
                (outgoing, 10, 2, b'', 0, 'SEND'), (incoming, 30, 18, b'', 0, 'RECV'),
                (outgoing, 11, 16, packet(0x90, struct.pack('<IB', 42, 1), 'SEND').raw, .1, 'SEND'),
                (incoming, 31, 16, packet(0xb4, struct.pack('<I', 42) + b'one\0').raw, .2, 'RECV'),
                (incoming, 43, 16, packet(0xb4, struct.pack('<I', 42) + b'two\0').raw, 2.2, 'RECV')):
                session.write('tcp_segment', endpoints=endpoints, sequence=sequence, flags=flags,
                              data=data, timestamp=timestamp, direction=direction)
            path = session.path
            session.close()
            report = analyze(path, definitions)
            self.assertEqual(report['timelines'][0]['source_ref'], str(Path(path).resolve()))
            self.assertEqual(report['timelines'][0]['candidates'][0]['duration_ms'], 2000)
            comparison = compare([path, path], definitions)
            self.assertEqual(len(comparison['sources']), 1)
            self.assertEqual(len(comparison['timelines']), 1)

    def test_server_close_preserves_aborted_wait_and_ack_without_false_prompt_overlap(self):
        from tests.unit.test_timeout_merging import trial
        for prompt in (0xb5,0xb7,0x142,0x1d4,0xb6):
            item=trial(prompt=prompt)
            # trial supplies an observed unanswered request followed by marked server close.
            item.steps[-1]['timestamp']=61
            close=item.steps[-1]
            item.steps.append(dict(kind='dismiss',fields={},timestamp=62,packet_index=99,
                packet_id=0x146,direction='SEND',connection='flow',source='TEST',reply_to=len(item.steps)-1))
            close['reply']=len(item.steps)-1
            result=build_timeline(item)
            with self.subTest(prompt=prompt):
                self.assertIn('unanswered_termination',result['quality_flags'])
                self.assertNotIn('overlapping_prompt',result['quality_flags'])
                aborted=next(w for w in result['waits'] if w.get('termination_reason'))
                self.assertFalse(aborted['complete'])
                self.assertIsNone(aborted['duration_ms'])
                self.assertEqual(aborted['termination_packet_index'],close['packet_index'])
                self.assertEqual(result['waits'][-1]['prompt_kind'],'close')
                self.assertTrue(result['waits'][-1]['complete'])
                self.assertEqual(result['candidates'],[])
        item=trial()
        item.steps[-1]['timeout_prompt_step_index']=999
        result=build_timeline(item)
        self.assertIn('overlapping_prompt',result['quality_flags'])
        self.assertNotIn('unanswered_termination',result['quality_flags'])

    def test_player_notification_rows_preserve_npc_timing_and_bound_details(self):
        from reconstruction.speech_origin import index_player_notifications
        item=observed()
        for index,step in enumerate(item.steps):step['packet_index']=index*10
        baseline=build_timeline(item)
        record=dict(kind='overhead',packet_id=0x8b3,direction='RECV',capture_session=item.capture_session,
            flow_id=item.flow_id,conversation_id=item.id,conversation_actor_id=item.actor_id,actor_id=9000,
            entity_kind='PLAYER',association_basis='active_dialogue_same_flow_player_notification',
            after_step_index=1,packet_index=15,timestamp=1,fields={'text':'notice'},context='during_dialogue')
        records=[record,copy.deepcopy(record),dict(record,flow_id='other'),dict(record,after_step_index=99),
                 dict(record,packet_index=25)]
        before=copy.deepcopy(item)
        result=build_timeline(item,player_notifications=index_player_notifications(records))
        self.assertEqual(result['player_notification_count'],1)
        self.assertEqual(result['waits'],baseline['waits'])
        self.assertEqual(result['candidates'],baseline['candidates'])
        self.assertEqual(result['quality_flags'],baseline['quality_flags'])
        self.assertEqual([row for row in result['rows'] if row.get('track')!='player_notification'],baseline['rows'])
        row=next(row for row in result['rows'] if row.get('track')=='player_notification')
        self.assertEqual(row['actor_id'],9000)
        self.assertEqual(row['conversation_actor_id'],42)
        self.assertFalse(row['candidate']);self.assertIsNone(row['delta_ms']);self.assertIsNone(row['wait_duration_ms'])
        self.assertEqual(item,before)
        many=[dict(record,after_step_index=2,packet_index=100+i,timestamp=3+i) for i in range(1005)]
        bounded=build_timeline(item,player_notifications=index_player_notifications(many))
        self.assertEqual(bounded['player_notification_count'],1005)
        self.assertEqual(bounded['player_notification_omitted'],5)
        self.assertEqual(sum(row.get('track')=='player_notification' for row in bounded['rows']),1000)
        self.assertEqual(bounded['candidates'],baseline['candidates'])


if __name__ == '__main__':
    unittest.main()
