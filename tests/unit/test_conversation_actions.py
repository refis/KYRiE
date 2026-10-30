import json
import struct
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.conversation_actions import load_status_ids, STATUS_MAP
from tests.support.world import map_packet, actor_packet, packet
from tests.support.display import variable
from tests.support.dialogue import packet as dialogue_packet


class ConversationActionTests(unittest.TestCase):
    def opened(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        def consume(event):
            event = replace(event, timestamp=float(store.packet_ordinal + 1))
            world.apply(event, packet_index=store.packet_ordinal)
            store.apply(event)
        consume(map_packet('0k81@toy.gat'))
        consume(packet(0x283, struct.pack('<I', 777)))
        for actor, name in ((42, 'Owner_0k8'), (43, 'Target_0k8')):
            event = actor_packet(actor_id=actor, name=name)
            raw = bytearray(event.raw)
            struct.pack_into('<I', raw, 19, 0)
            consume(replace(event, raw=bytes(raw)))
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'hello\0', flow=None, connection='flow-a'))
        return store, consume

    def visibility(self, consume, actor, options):
        consume(packet(0x229, struct.pack('<IHHIB', actor, 0, 0, options, 0)))

    def test_visibility_targets_and_unittalk_are_inline_and_keep_packet_order(self):
        store, consume = self.opened()
        consume(packet(0x2b4, struct.pack('<I', 100)))
        self.visibility(consume, 43, 2)
        self.visibility(consume, 43, 0)
        self.visibility(consume, 42, 4)
        self.visibility(consume, 42, 0)
        consume(variable(0x8d, struct.pack('<I', 43) + b'outside words\0', 'flow-a'))
        consume(variable(0x8d, struct.pack('<I', 42) + b'own words\0', 'flow-a'))
        consume(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        before = deepcopy(item)
        code = AurigaRenderer().render(item)
        expected = ['mes "hello";', 'delquest 100;', 'hideonnpc getmdnpcname("Target");',
                    'hideoffnpc getmdnpcname("Target");', 'cloakonnpc;', 'cloakoffnpc;',
                    'unittalk getnpcid(0,getmdnpcname("Target")),"outside words";',
                    'unittalk "own words";', 'close;']
        positions = [code.index(command) for command in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(item, before)
        self.assertFalse(build_merged([('', item)])['excluded'])

    def test_progress_wait_notification_preserves_reply_link_and_is_deferred_with_comment(self):
        store, consume = self.opened()
        consume(packet(0xb5, struct.pack('<I', 42)))
        consume(packet(0x2f0, struct.pack('<II', 0xaabbcc, 7)))
        consume(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
        consume(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(item.steps[3]['reply_to'], 2)
        code = AurigaRenderer().render(item)
        self.assertIn('progressbar 7,0xAABBCC;', code)
        self.assertIn('入力待ち中の通知', code)
        self.assertLess(code.index('next;'), code.index('progressbar 7,'))
        timeline = store.snapshot()['timelines'][0]
        self.assertTrue(any(row['kind'] == 'progress_action' for row in timeline['rows']))

    def test_status_conversion_starts_ends_and_keeps_unmapped_or_complex_arguments_as_comments(self):
        store, consume = self.opened()
        def status(effect, flag=1, value2=0, actor=777):
            consume(packet(0x983, struct.pack('<HIBIIIII', effect, actor, flag, 30000, 12345, 10, value2, 0)))
        mapping = load_status_ids()
        effect, converted = next((int(k), row['script_id']) for k, row in mapping.items() if row['symbol'] == 'SC_MONSTER_TRANSFORM')
        status(effect)
        status(effect, flag=0)
        status(65535)
        status(effect, value2=99)
        status(10, actor=888)
        consume(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(len(item.actions), 4)
        code = AurigaRenderer().render(item)
        self.assertIn(f'sc_start {converted},30000,10;', code)
        self.assertIn(f'sc_end {converted};', code)
        self.assertNotIn('sc_start 65535,', code)
        self.assertEqual(code.count('状態異常のIDまたは引数は未対応'), 2)
        self.assertEqual(item.actions[0]['fields']['tick'], 12345)
        self.assertFalse(build_merged([('', item)])['excluded'])

    def test_status_id_table_distinguishes_namespaces_and_nonidentity_ids(self):
        mapping = load_status_ids()
        self.assertTrue(any(int(icon) != row['script_id'] for icon, row in mapping.items()))
        self.assertNotIn('65535', mapping)
        with self.assertRaises(ValueError):
            load_status_ids(STATUS_MAP, target='rathena')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ids.json'
            document = json.loads(STATUS_MAP.read_text(encoding='utf-8'))
            document['entries']['10']['symbol'] = 'SC_X;end'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_status_ids(path, target='auriga')

    def test_rathena_status_ids_and_dialogue_switch_without_auriga_instance_commands(self):
        from reconstruction.emulator_profiles import set_target, profile, target
        previous = target()
        try:
            set_target('rathena')
            mapping = load_status_ids()
            self.assertTrue(mapping)
            self.assertTrue(any(int(icon) != row['script_id'] for icon, row in mapping.items()))
            self.assertEqual(mapping['0']['symbol'], 'SC_PROVOKE')
            self.assertEqual(mapping['0']['script_id'], 20)
            self.assertEqual(mapping['0']['source_symbol'], 'EFST_PROVOKE')
            self.assertEqual(mapping['621']['argument_policy'], 'val1_only')
            self.assertEqual(mapping['665']['argument_policy'], 'val1_only')
            store, consume = self.opened()
            consume(packet(0x2f0, struct.pack('<II', 0xaabbcc, 7)))
            consume(variable(0x8d, struct.pack('<I', 42) + b'own words\0', 'flow-a'))
            consume(packet(0xb6, struct.pack('<I', 42)))
            code = AurigaRenderer().render(store.sessions[0])
            self.assertIn('progressbar "0xAABBCC",7;', code)
            self.assertIn('npctalk "own words";', code)
            self.assertNotIn('getmdmapname', code)
            self.assertNotIn('getmdnpcname', code)
            dialogue = json.loads(profile('dialogue.json').read_text(encoding='utf-8'))
            self.assertEqual(dialogue['instance_map_reference'], 'instance_mapname({name})')
            self.assertEqual(dialogue['instance_npc_reference'], 'instance_npcname({name})')
            self.assertEqual(dialogue['number'], 'input .@gpa_number;')
            self.assertEqual(dialogue['text'], 'input .@gpa_text$;')
            self.assertNotIn("'@", json.dumps({'number': dialogue['number'], 'text': dialogue['text']}))
            store, consume = self.opened()
            consume(packet(0xb5, struct.pack('<I', 42)))
            consume(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            consume(packet(0x142, struct.pack('<I', 42)))
            consume(packet(0x143, struct.pack('<Ii', 42, 7), direction='SEND'))
            consume(packet(0xb6, struct.pack('<I', 42)))
            code = AurigaRenderer().render(store.sessions[0])
            self.assertIn('input .@gpa_number;', code)
            self.assertNotIn("input '@", code)
        finally:
            set_target(previous)

    def test_same_path_action_variations_are_not_silently_merged(self):
        trials = []
        for seconds in (2, 4):
            store, consume = self.opened()
            consume(packet(0x2f0, struct.pack('<II', 123, seconds)))
            consume(packet(0xb6, struct.pack('<I', 42)))
            trials.append((str(seconds), store.sessions[0]))
        report = build_merged(trials)
        self.assertEqual(report['groups'][0]['presentation_check']['conflicts'], 1)
        code = AurigaRenderer().render_merged(report['groups'][0])
        self.assertIn('progressbar 2,', code)
        self.assertIn('progressbar 4,', code)

    def test_malformed_and_capacity_limited_actions_do_not_shift_input_replies(self):
        store, consume = self.opened()
        consume(packet(0xb5, struct.pack('<I', 42)))
        consume(packet(0x983, b'bad'))
        store.action_count = 10000
        consume(packet(0x2f0, struct.pack('<II', 0, 2)))
        consume(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
        self.assertEqual(store.sessions[0].steps[-1]['reply_to'], 2)
        self.assertFalse(store.sessions[0].actions)
        self.assertGreaterEqual(store.issue_count, 2)

    def test_status_ticks_do_not_create_false_conflicts_and_numeric_conversion_is_explicit(self):
        trials = []
        mapping = load_status_ids()
        effect, converted = next((int(k), row['script_id']) for k, row in mapping.items() if row['symbol'] == 'SC_MONSTER_TRANSFORM')
        for tick in (12345, 54321):
            store, consume = self.opened()
            consume(packet(0x983, struct.pack('<HIBIIIII', effect, 777, 1, 30000, tick, 10, 0, 0)))
            consume(packet(0xb6, struct.pack('<I', 42)))
            trials.append((str(tick), store.sessions[0]))
        group = build_merged(trials)['groups'][0]
        code = AurigaRenderer().render_merged(group)
        self.assertEqual(code.count(f'sc_start {converted},30000,10;'), 1)
        mapping = load_status_ids()
        source, converted = next((int(key), value['script_id']) for key, value in mapping.items()
                                 if int(key) != value['script_id'])
        store, consume = self.opened()
        consume(packet(0x43f, struct.pack('<HIBIIII', source, 777, 0, 0, 0, 0, 0)))
        consume(packet(0xb6, struct.pack('<I', 42)))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('sc_end ' + str(converted) + ';', code)
        self.assertNotIn('sc_end ' + str(source) + ';', code)

    def test_basic_buff_icon_does_not_invent_an_unobserved_skill_level(self):
        store, consume = self.opened()
        consume(packet(0x43f, struct.pack('<HIBIIII', 10, 777, 1, 30000, 0, 0, 0)))
        consume(packet(0xb6, struct.pack('<I', 42)))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('状態異常のIDまたは引数は未対応', code)
        self.assertNotIn('sc_start 10,', code)

    def test_timeout_prefix_with_prior_action_matches_answered_continuation_without_duplicate_command(self):
        trials = []
        for reply in (False, True):
            store, consume = self.opened()
            consume(packet(0x2f0, struct.pack('<II', 0, 2)))
            consume(packet(0xb5, struct.pack('<I', 42)))
            if reply:
                consume(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
                consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'continued\0', flow=None, connection='flow-a'))
            consume(packet(0xb6, struct.pack('<I', 42)))
            trials.append((str(reply), store.sessions[0]))
        report = build_merged(trials)
        self.assertFalse(report['excluded'])
        self.assertEqual(len(report['groups']), 1)
        group = report['groups'][0]
        self.assertEqual(len(group['timeout_normalizations']), 1)
        self.assertEqual(AurigaRenderer().render_merged(group).count('progressbar 2,'), 1)


class ProgressTraceTests(unittest.TestCase):
    def test_report_and_same_dialogue_followup_are_observations_only(self):
        store, consume = ConversationActionTests().opened()
        consume(packet(0x2f0, struct.pack('<II', 0xaabbcc, 1)))
        before = deepcopy(store.sessions[0])
        consume(packet(0x2f1, direction='SEND'))
        self.assertEqual(store.sessions[0], before)
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'continued\0', flow=None, connection='flow-a'))
        trace = store.snapshot()['progress_observations']
        rows = trace['observations']
        self.assertEqual([r['kind'] for r in rows], ['progress_start', 'progress_client_report', 'progress_followup'])
        self.assertEqual(rows[1]['client_report_packet_index'], rows[1]['packet_index'])
        self.assertEqual(rows[2]['start_packet_index'], rows[0]['packet_index'])
        self.assertFalse(any(r['success_confirmed'] for r in rows))
        self.assertFalse(trace['server_timer_inferred'])
        self.assertEqual(AurigaRenderer().render(store.sessions[0]).count('progressbar 1,'), 1)

    def test_abort_wrong_flow_capture_and_boundary_do_not_leak_associations(self):
        from reconstruction.progress import ProgressTrace
        trace = ProgressTrace()
        start = packet(0x2f0, struct.pack('<II', 0, 1))
        trace.observe(start, 0, 1)
        trace.observe(packet(0x2f1, connection='other', direction='SEND'), 0, 2)
        self.assertTrue(trace.records[-1]['orphan'])
        trace.observe(packet(0x2f2), 0, 3)
        self.assertEqual(trace.records[-1]['start_packet_index'], 1)
        trace.observe(packet(0x2f1, direction='SEND'), 0, 4)
        self.assertTrue(trace.records[-1]['orphan'])
        trace.observe(start, 0, 5)
        trace.observe(packet(0x90, struct.pack('<IB', 99, 1), direction='SEND'), 0, 6)
        self.assertEqual(trace.records[-1]['kind'], 'progress_boundary')
        trace.observe(start, 0, 7)
        trace.begin_capture()
        trace.observe(packet(0x2f1, direction='SEND'), 1, 8)
        self.assertTrue(trace.records[-1]['orphan'])
        self.assertEqual(trace.capture_resets, 1)

    def test_overlap_invalid_layout_and_storage_limits_are_explicit(self):
        from reconstruction.progress import ProgressTrace
        trace = ProgressTrace(max_records=4, max_pending=1)
        start = packet(0x2f0, struct.pack('<II', 0, 1))
        trace.observe(start, 0, 1)
        trace.observe(start, 0, 2)
        trace.observe(packet(0x2f1, direction='SEND'), 0, 3)
        self.assertTrue(trace.records[-1]['association_ambiguous'])
        self.assertIsNone(trace.records[-1]['start_packet_index'])
        trace.observe(start, 0, 4)
        self.assertFalse(trace.records[-1]['association_ambiguous'])
        trace.observe(replace(start, connection='other'), 0, 5)
        self.assertEqual(trace.pending_evicted, 1)
        trace.observe(packet(0x2f1, b'bad', connection='other', direction='SEND'), 0, 6)
        self.assertEqual(trace.records[-1]['kind'], 'progress_invalid')
        self.assertFalse(trace.pending)
        self.assertEqual(trace.dropped, 2)
        snapshot = trace.snapshot()
        snapshot['observations'].clear()
        self.assertEqual(len(trace.records), 4)

    def test_elapsed_is_not_inferred_from_ambiguous_or_invalid_timestamps(self):
        from reconstruction.progress import ProgressTrace
        for start_time, report_time in ((float('nan'), 1), (2, 1), (-1e308, 1e308)):
            trace = ProgressTrace()
            trace.observe(packet(0x2f0, struct.pack('<II', 0, 1), timestamp=start_time), 0, 1)
            trace.observe(packet(0x2f1, timestamp=report_time, direction='SEND'), 0, 2)
            self.assertIsNone(trace.records[-1]['observed_elapsed_ms'])
        trace = ProgressTrace()
        for index in (1, 2):
            trace.observe(packet(0x2f0, struct.pack('<II', 0, 1), timestamp=index), 0, index)
        trace.observe(packet(0x2f1, timestamp=3, direction='SEND'), 0, 3)
        self.assertIsNone(trace.records[-1]['observed_elapsed_ms'])


class DialogueLayoutTests(unittest.TestCase):
    def test_layouts_validate_lengths_and_preserve_all_raw_values(self):
        from reconstruction.dialogue import decode_dialogue
        cases=[(0xba1,b'\xff','dialogue_alignment',{'alignment':255}),
               (0xba2,struct.pack('<II',0,0xffffffff),'dialogue_size',{'height':0,'width':0xffffffff}),
               (0xba3,struct.pack('<II',100,200),'dialogue_position',{'x':100,'y':200}),
               (0xbb5,struct.pack('<II',0xffffffff,0),'dialogue_position',{'x':0xffffffff,'y':0})]
        for pid,body,kind,fields in cases:
            with self.subTest(pid=pid):
                event=packet(pid,body)
                self.assertEqual(decode_dialogue(event),(kind,None,fields))
                self.assertIsNone(decode_dialogue(replace(event,direction='SEND')))
                for raw in (event.raw[:-1],event.raw+b'\0'):
                    with self.assertRaises(ValueError):decode_dialogue(replace(event,raw=raw))

    def test_layout_context_generates_only_for_active_owner_without_carrying_across_boundaries(self):
        store,consume=ConversationActionTests().opened()
        event=packet(0xba2,struct.pack('<II',300,400))
        before=deepcopy(store.sessions[0])
        consume(event)
        row=store.presentation_observations[-1]
        self.assertEqual(row['conversation_id'],before.id)
        self.assertEqual(row['conversation_actor_id'],42)
        self.assertEqual(row['conversation_start_packet_index'],before.steps[0]['packet_index'])
        self.assertIsNone(row['actor_id'])
        self.assertFalse(row['cause_confirmed'])
        self.assertEqual(store.sessions[0].steps,before.steps)
        self.assertEqual(len(store.sessions[0].actions),1)
        consume(packet(0xb5,struct.pack('<I',42)))
        consume(event)
        self.assertEqual(store.presentation_observations[-1]['context'],'input_wait')
        consume(replace(event,connection='other'))
        self.assertNotIn('conversation_id',store.presentation_observations[-1])
        consume(packet(0xb6,struct.pack('<I',42)))
        consume(event)
        self.assertEqual(store.presentation_observations[-1]['context'],'close_wait')
        consume(packet(0x146,struct.pack('<I',42),direction='SEND'))
        consume(event)
        self.assertEqual(store.presentation_observations[-1]['context'],'outside_dialogue')
        self.assertNotIn('conversation_id',store.presentation_observations[-1])
        store.apply(event,session=1)
        self.assertNotIn('conversation_id',store.presentation_observations[-1])
        self.assertEqual(len(store.sessions),1)
        self.assertEqual(AurigaRenderer().render(store.sessions[0]).count('messize 300,400;'),1)

    def test_layout_comparison_requires_same_conversation_start_and_scene(self):
        from tests.support.event_trials import observation
        from reconstruction.event_trials import compare_event_trials
        from reconstruction.event_timer_export import build_timer_candidate
        def anchor(when):
            return observation(when,kind='dialogue_start',anchor_type='dialogue_start',
                context='comparison_anchor',fields={'start_kind':'open'})
        def layout(when,start):
            return observation(when,kind='dialogue_size',context='during_dialogue',
                actor_id=None,target_observed=False,entity_kind='unresolved',npc={},
                fields={'height':300,'width':400},map_context={'map_name':'test.gat','map_generation':1},
                association_basis='same_flow_active_dialogue_layout',conversation_start_packet_index=start)
        rows=[anchor(0),layout(1,0),anchor(10),layout(11,1000)]
        before=deepcopy(rows)
        report=compare_event_trials(rows,[0,2],window_ms=2000)
        self.assertEqual([len(t['events']) for t in report['trials']],[2,2])
        self.assertEqual(rows,before)
        with self.assertRaises(ValueError):build_timer_candidate(report,0,[100,1100],confirmed=True)
        for updates in ({'conversation_start_packet_index':999}, {'map_context':None},
                        {'flow_id':'other'}, {'capture_session':1}, {'context':'input_wait'},
                        {'map_context':{'map_name':'test.gat','map_generation':2}}):
            changed=deepcopy(rows)
            changed[1].update(updates)
            result=compare_event_trials(changed,[0,2],window_ms=2000)
            self.assertEqual(len(result['trials'][0]['events']),1)

    def test_layout_commands_keep_order_and_merged_differences(self):
        trials=[]
        for width in (400,500):
            store,consume=ConversationActionTests().opened()
            consume(packet(0xba2,struct.pack('<II',300,width)))
            consume(packet(0xba3,struct.pack('<II',100,200)))
            consume(packet(0xba1,b'\x02'))
            consume(dialogue_packet(0xb4,struct.pack('<I',42)+b'after\0',flow=None,connection='flow-a'))
            consume(packet(0xbb5,struct.pack('<II',50,60)))
            consume(packet(0xb6,struct.pack('<I',42)))
            item=store.sessions[0]
            before=deepcopy(item)
            code=AurigaRenderer().render(item)
            expected=['mes "hello";',f'messize 300,{width};','mespos 100,200;',
                      'mesalign 2;','mes "after";','mespos 50,60;','close;']
            positions=[code.index(value) for value in expected]
            self.assertEqual(positions,sorted(positions))
            self.assertEqual(item,before)
            trials.append((str(width),item))
        report=build_merged(trials)
        self.assertFalse(report['excluded'])
        group=report['groups'][0]
        self.assertEqual(group['presentation_check']['conflicts'],1)
        code=AurigaRenderer().render_merged(group)
        self.assertIn('messize 300,400;',code)
        self.assertIn('messize 300,500;',code)
        absent=deepcopy(trials[0][1])
        absent.id=3
        absent.actions=[]
        missing=build_merged([trials[0],('absent',absent)])
        self.assertEqual(missing['groups'][0]['presentation_check']['conflicts'],1)
        self.assertIn('messize 300,400;',AurigaRenderer().render_merged(missing['groups'][0]))

    def test_waiting_layout_retains_reply_link_and_defers_with_existing_warning(self):
        store,consume=ConversationActionTests().opened()
        consume(packet(0xb5,struct.pack('<I',42)))
        consume(packet(0xba2,struct.pack('<II',300,400)))
        consume(packet(0xba1,b'\x01'))
        consume(packet(0xb9,struct.pack('<I',42),direction='SEND'))
        consume(packet(0xb6,struct.pack('<I',42)))
        item=store.sessions[0]
        self.assertEqual(item.steps[3]['reply_to'],2)
        self.assertEqual(len(item.actions),2)
        code=AurigaRenderer().render(item)
        self.assertIn('入力待ち中の通知',code)
        self.assertLess(code.index('next;'),code.index('messize 300,400;'))
        self.assertLess(code.index('messize 300,400;'),code.index('mesalign 1;'))
        self.assertFalse(build_merged([('',item)])['excluded'])

    def test_layout_generation_validates_fields_and_uses_external_templates(self):
        from reconstruction.conversation_actions import validate_actions
        store,consume=ConversationActionTests().opened()
        consume(packet(0xba1,b'\x02'))
        consume(packet(0xb6,struct.pack('<I',42)))
        item=store.sessions[0]
        for updates in ({'alignment':True},{'alignment':256},{'alignment':-1},{'alignment':'2'}):
            invalid=deepcopy(item)
            invalid.actions[0]['fields']=updates
            with self.assertRaises(ValueError):validate_actions(invalid)
        renderer=AurigaRenderer()
        profile=deepcopy(renderer.templates)
        profile['dialogue_alignment']='mesalign {alignment}; // custom'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'dialogue.json'
            path.write_text(json.dumps(profile),encoding='utf-8')
            self.assertIn('mesalign 2; // custom',AurigaRenderer(path).render(item))
            for key in ('dialogue_size','dialogue_position','dialogue_alignment'):profile.pop(key)
            path.write_text(json.dumps(profile),encoding='utf-8')
            self.assertIn('mesalign 2;',AurigaRenderer(path).render(item))
