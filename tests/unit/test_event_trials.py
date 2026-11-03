from copy import deepcopy
from unittest.mock import patch
import unittest
from reconstruction.event_trials import compare_event_trials
from tests.support.event_trials import observation


class EventTrialTests(unittest.TestCase):
    def test_anchor_comparison_keeps_target_scope_input_wait_and_variants_separate(self):
        rows = [observation(0), observation(.2, 99, actor_id=99),
                observation(.5, 88, context='input_wait'), observation(1, 9),
                observation(1.2, 99, npc=dict(observation(0)['npc'], map_generation=2)),
                observation(10), observation(11.01, 9), observation(20), observation(21, 9)]
        before = deepcopy(rows)
        report = compare_event_trials(rows, [0, 5, 7], window_ms=2000)
        self.assertEqual(report['status'], 'repeated_consistent')
        self.assertEqual(report['trials'][0]['excluded_input_or_parallel'], 1)
        self.assertEqual([len(trial['events']) for trial in report['trials']], [2, 2, 2])
        self.assertEqual(report['variants'][0]['timings'][0]['median_ms'], 1000)
        self.assertFalse(report['coverage_verified'])
        self.assertFalse(report['server_timer_confirmed'])
        self.assertEqual(rows, before)
        changed = deepcopy(rows)
        changed[-1]['fields']['value'] = 10
        different = compare_event_trials(changed, [0, 5, 7], window_ms=2000)
        self.assertEqual(different['status'], 'observed_difference')
        self.assertEqual(len(different['variants']), 2)
        self.assertFalse(different['cause_confirmed'])
        changed = deepcopy(rows)
        changed[-1]['timestamp'] = 21.5
        self.assertEqual(compare_event_trials(changed, [0, 5, 7], window_ms=2000)['status'], 'repeated_variable')
        self.assertEqual(compare_event_trials(rows[:7], [0, 5], window_ms=2000)['status'], 'insufficient_repeats')
        self.assertEqual(compare_event_trials([observation(0), observation(10), observation(20)], [0, 1, 2])
                         ['status'], 'no_followup_observed')
        report['trials'][0]['events'][0]['observation']['npc']['name'] = 'changed'
        self.assertEqual(rows, before)

    def test_dialogue_action_projection_keeps_targets_waits_duplicates_and_raw_evidence(self):
        import struct
        from reconstruction.comparison_anchors import comparison_rows
        from tests.unit.test_conversation_actions import ConversationActionTests
        from tests.support.world import packet
        store,consume=ConversationActionTests().opened()
        consume(packet(0x2f0,struct.pack('<II',0xaabbcc,2)))
        consume(packet(0x983,struct.pack('<HIBIIIII',10,777,1,30000,12345,1,0,0)))
        consume(packet(0x229,struct.pack('<IHHIB',43,0,0,2,0)))
        consume(packet(0x1b0,struct.pack('<IBI',43,0,139)))
        consume(packet(0xf2,struct.pack('<HH',2,100)))
        consume(packet(0xb5,struct.pack('<I',42)))
        consume(packet(0x2f0,struct.pack('<II',0xaabbcc,3)))
        consume(packet(0xb9,struct.pack('<I',42),direction='SEND'))
        consume(packet(0x2f0,struct.pack('<II',0xaabbcc,4)))
        item=store.sessions[0]
        duplicate=deepcopy(item.actions[0]);item.actions.append(duplicate)
        review=deepcopy(next(row for row in item.actions if row['kind']=='script_command'))
        review['fields']['review_only']=True;item.actions.append(review)
        outside=deepcopy(next(row for row in item.actions if row['kind']=='npc_display_action'))
        outside['fields']['outside']=True;item.actions.append(outside)
        unresolved=deepcopy(outside);unresolved['fields']['outside']=False
        unresolved['fields']['target']['name']='';item.actions.append(unresolved)
        before=deepcopy(item)
        default=comparison_rows(store,'dialogue_start')
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        actions=[row for row in rows if row.get('comparison_scope')=='dialogue_owner']
        self.assertEqual(len(actions),len(item.actions)-1)
        self.assertEqual({row['kind'] for row in actions},{'progress_action','status_action','visibility_action','npc_display_action','script_command'})
        self.assertFalse(any(row.get('comparison_scope') for row in default))
        status=next(row for row in actions if row['kind']=='status_action')
        self.assertNotIn('tick',status['fields'])
        self.assertEqual(status['raw_fields']['tick'],12345)
        self.assertEqual(status['effect_target'],{'role':'player'})
        target=next(row for row in actions if row['kind']=='visibility_action')
        self.assertEqual(target['actor_id'],42)
        self.assertEqual(target['effect_target']['name'],'Target')
        self.assertEqual(target['raw_fields']['target']['name'],'Target_0k8')
        self.assertEqual([row['context'] for row in actions if row['kind']=='progress_action'],['during_dialogue','input_wait','during_dialogue'])
        self.assertIn('review_only',[row['context'] for row in actions])
        self.assertIn('outside_visibility',[row['context'] for row in actions])
        self.assertIn('target_unresolved',[row['context'] for row in actions])
        self.assertTrue(all(row['cause_confirmed'] is False for row in actions))
        self.assertEqual(item,before)
        with patch('reconstruction.comparison_anchors.MAX_COMPARISON_ROWS',4):
            with self.assertRaises(ValueError):comparison_rows(store,'dialogue_start',include_actions=True)
        item.actions[0]['flow_id']='wrong-flow'
        with self.assertRaises(ValueError):comparison_rows(store,'dialogue_start',include_actions=True)
        self.assertEqual(comparison_rows(store,'dialogue_start'),default)

    def test_action_comparison_ignores_status_tick_distinguishes_targets_and_remaps_selection(self):
        from types import SimpleNamespace
        from tests.support.branches import conversation
        from reconstruction.comparison_anchors import comparison_rows
        from reconstruction.event_trials import trial_review
        from reconstruction.event_timer_export import build_timer_candidate
        store=SimpleNamespace(sessions=[],presentation_observations=[],map_arrival_anchors=[])
        for number in range(3):
            item=conversation(identifier=number+1)
            item.started=number*10
            for index,step in enumerate(item.steps):step.update(timestamp=number*10+index*.1,packet_index=number*100+index*10)
            def action(kind,fields,packet_id,offset):
                return dict(kind=kind,fields=fields,capture_session=item.capture_session,flow_id=item.flow_id,
                    timestamp=number*10+.15+offset/1000,packet_index=number*100+15+offset,
                    packet_id=packet_id,direction='RECV',connection='receive',source='TEST',after_step_index=1,cause_confirmed=False)
            item.actions=[action('status_action',dict(effect_id=10,flag=1,remaining_ms=30000,value1=1,value2=0,value3=0,tick=number*100),0x983,0),
                action('visibility_action',dict(commands=['hideonnpc'],target=dict(name='Target',map_name='test.gat'),options=2,previous_options=0),0x229,1)]
            store.sessions.append(item)
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        anchors=[index for index,row in enumerate(rows) if row.get('anchor_type')=='dialogue_start']
        report=compare_event_trials(rows,anchors,window_ms=2000)
        self.assertEqual(report['status'],'repeated_consistent')
        self.assertEqual([len(trial['events']) for trial in report['trials']],[3,3,3])
        self.assertFalse(report['server_timer_confirmed'])
        with self.assertRaises(ValueError):build_timer_candidate(report,0,[0,100,200],confirmed=True)
        import tempfile
        from pathlib import Path
        from storage.event_trial_selection import save_selection,load_selection
        from tests.unit.test_event_trial_selection import raw_log
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'capture.jsonl';raw_log(source,'actions')
            saved=Path(folder)/'selection.json'
            save_selection(saved,rows,anchors,{0:str(source)},2000)
            remapped=deepcopy(rows)
            for row in remapped:row['capture_session']=7;row['packet_index']+=10000
            self.assertEqual(load_selection(saved,remapped,{7:str(source)}),(anchors,2000))
            with self.assertRaises(ValueError):load_selection(saved,comparison_rows(store,'dialogue_start'),{0:str(source)})
        store.sessions[-1].actions[-1]['fields']['target']['name']='Other'
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        report=compare_event_trials(rows,anchors,window_ms=2000)
        self.assertEqual(report['status'],'observed_difference')
        self.assertEqual(trial_review(report,2,rows)['differences'][2]['status'],'target_changed')

    def test_multi_log_instance_actions_keep_per_trial_scope_and_remap_saved_anchors(self):
        from tests.support.event_trials import instance_action_store
        from reconstruction.comparison_anchors import comparison_rows
        store=instance_action_store()
        before=deepcopy(store.sessions)
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        anchors=[index for index,row in enumerate(rows) if row.get('anchor_type')=='dialogue_start']
        report=compare_event_trials(rows,anchors,window_ms=2000)
        self.assertEqual(report['status'],'repeated_consistent')
        for trial in report['trials']:
            self.assertEqual(len(trial['events']),2)
            self.assertEqual({event['observation']['capture_session'] for event in trial['events']},{trial['anchor']['capture_session']})
            self.assertEqual(trial['events'][1]['observation']['effect_target']['name'],'Target')
        self.assertEqual(store.sessions,before)
        import tempfile
        from pathlib import Path
        from storage.event_trial_selection import save_selection,load_selection
        from tests.unit.test_event_trial_selection import raw_log
        with tempfile.TemporaryDirectory() as folder:
            sources={number:str(Path(folder)/f'{number}.jsonl') for number in (1,2,3)}
            for number,path in sources.items():raw_log(Path(path),'instance-'+str(number))
            saved=Path(folder)/'anchors.json'
            save_selection(saved,rows,anchors,sources,2000)
            mapping={1:20,2:3,3:12}
            remapped=deepcopy(rows)
            for row in remapped:
                row['capture_session']=mapping[row['capture_session']]
                row['packet_index']+=10000
            remapped.sort(key=lambda row:(row['capture_session'],row['packet_index']))
            indices,window=load_selection(saved,remapped,{mapping[key]:value for key,value in sources.items()})
            self.assertEqual(indices,[4,0,2])
            self.assertEqual(window,2000)
            self.assertEqual(compare_event_trials(remapped,indices,window_ms=window)['status'],'repeated_consistent')

        for item in store.sessions:
            floor=deepcopy(item.actions[0])
            floor.update(kind='script_command',packet_id=0xadd,packet_index=floor['packet_index']+1,timestamp=.16,
                fields=dict(command='dropitem',arguments=dict(map_name=item.npc['map_name'],x=10,y=20,
                    item_id=501,amount=1,extra_lifetime_ms=0),review_only=False,reason=''))
            item.actions.append(floor)
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        anchors=[index for index,row in enumerate(rows) if row.get('anchor_type')=='dialogue_start']
        report=compare_event_trials(rows,anchors,window_ms=2000)
        self.assertEqual(report['status'],'repeated_consistent')
        floor=next(row for row in rows if row['kind']=='script_command')
        self.assertEqual(floor['fields']['arguments']['map_name'],'1@toy.gat')
        self.assertEqual(floor['raw_fields']['arguments']['map_name'],'aB11@toy.gat')
        store.sessions[-1].actions[-1]['fields']['arguments']['map_name']='cD21@toy.gat'
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        report=compare_event_trials(rows,anchors,window_ms=2000)
        from reconstruction.event_trials import trial_review
        self.assertEqual(trial_review(report,2,rows)['excluded_counts'],{'target_different_map':1})

    def test_instance_action_scope_and_partial_names_are_not_silently_unified(self):
        from tests.support.event_trials import instance_action_store
        from reconstruction.comparison_anchors import comparison_rows
        from reconstruction.event_trials import trial_review
        store=instance_action_store()
        original=deepcopy(store.sessions)
        store.sessions[2].actions[0]['fields']['target']=deepcopy(store.sessions[1].actions[0]['fields']['target'])
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        anchors=[index for index,row in enumerate(rows) if row.get('anchor_type')=='dialogue_start']
        report=compare_event_trials(rows,anchors,window_ms=2000)
        self.assertEqual([len(trial['events']) for trial in report['trials']],[2,2,1])
        review=trial_review(report,2,rows)
        self.assertEqual(review['excluded_counts'],{'target_different_map':1})
        self.assertEqual(review['excluded'][0]['observation']['observed_target']['map_name'],'cD21@toy.gat')
        store.sessions=deepcopy(original)
        store.sessions[2].actions[0]['fields']['target']['name']='Target_'
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        report=compare_event_trials(rows,anchors,window_ms=2000)
        self.assertEqual(trial_review(report,2,rows)['excluded_counts'],{'target_name_ambiguous':1})
        self.assertEqual(store.sessions[2].actions[0]['fields']['target']['name'],'Target_')
        for item in store.sessions:item.npc['name']='Owner_'
        rows=comparison_rows(store,'dialogue_start',include_actions=True)
        with self.assertRaisesRegex(ValueError,'省略'):
            compare_event_trials(rows,anchors,window_ms=2000)
        # Same observed owner and instance scope can still be compared; do not trim its name.
        repeat=deepcopy(rows[:2])
        for row in repeat:row['timestamp']+=10;row['packet_index']+=1000
        scoped=rows[:2]+repeat
        report=compare_event_trials(scoped,[0,2],window_ms=2000)
        self.assertEqual(report['npc_identity']['name'],'Owner_')
        self.assertEqual(report['status'],'insufficient_repeats')
        for row in repeat:
            row['npc']['map_generation']+=1;row['npc']['appearance']+=1
        self.assertEqual(compare_event_trials(scoped,[0,2],window_ms=2000)['status'],'insufficient_repeats')
        repeat[0]['actor_id']+=1
        with self.assertRaisesRegex(ValueError,'省略'):compare_event_trials(scoped,[0,2],window_ms=2000)

    def test_review_exposes_clock_failures_and_limit_without_changing_eligibility(self):
        from reconstruction.event_trials import trial_review
        from math import isnan
        rows=[observation(0),observation(.1,9,timestamp=float('nan'),packet_index=1),
              observation(.2,9,packet_index=2),observation(.15,9,packet_index=3),
              observation(10)]
        report=compare_event_trials(rows,[0,4],window_ms=2000)
        before=deepcopy(report)
        review=trial_review(report,0,rows)
        self.assertEqual(review['excluded_counts'],{'invalid_time':1,'time_reversed':1})
        self.assertIsNone(review['excluded'][0]['offset_ms'])
        self.assertEqual(review['excluded'][1]['observation']['packet_index'],3)
        self.assertEqual([row['observation']['packet_index'] for row in report['trials'][0]['events']],[0,2])
        self.assertEqual(report['trials'][0]['quality_flags'],['invalid_time'])
        self.assertEqual(report,before)
        self.assertTrue(isnan(rows[1]['timestamp']))
        many=[observation(0)]+[observation(index/10000,9) for index in range(1,1003)]+[observation(10)]
        report=compare_event_trials(many,[0,len(many)-1],window_ms=2000)
        review=trial_review(report,0,many,max_details=1)
        self.assertEqual(len(report['trials'][0]['events']),1000)
        self.assertEqual(review['excluded_counts'],{'event_limit':3})
        self.assertEqual(len(review['excluded']),1)
        self.assertEqual(review['omitted_details'],2)
        huge=[observation(0,timestamp=10**308,packet_index=0),
              observation(1,9,timestamp=0,packet_index=1),
              observation(10,timestamp=10**308,packet_index=2)]
        report=compare_event_trials(huge,[0,2])
        self.assertIsNone(trial_review(report,0,huge)['excluded'][0]['offset_ms'])

    def test_invalid_anchors_overlap_clock_and_limits_cannot_claim_valid_repetition(self):
        base = [observation(0), observation(1), observation(1.5, 9)]
        overlap = compare_event_trials(base, [0, 1], window_ms=2000)
        self.assertEqual(overlap['status'], 'no_eligible_trials')
        self.assertTrue(all('overlapping_windows' in row['quality_flags'] for row in overlap['trials']))
        invalid_clock = compare_event_trials([observation(0), observation(-1, 9), observation(10)], [0, 2])
        self.assertIn('invalid_time', invalid_clock['trials'][0]['quality_flags'])
        for changes in (dict(context='input_wait'), dict(timestamp=float('nan')), dict(timestamp=10**1000), dict(target_observed=False),
                        dict(entity_kind='MOB'), dict(npc={}), dict(fields=dict(value=99))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compare_event_trials([observation(0), observation(10, **changes)], [0, 1])
        for anchors in ([0], [0, 0], [0, 999], [False, 1]):
            with self.subTest(anchors=anchors), self.assertRaises(ValueError):
                compare_event_trials(base, anchors)
        for window in (0, 60001, True, float('nan')):
            with self.subTest(window=window), self.assertRaises(ValueError):
                compare_event_trials(base, [0, 1], window_ms=window)
        many = [observation(0)] + [observation(i / 10000, 9) for i in range(1, 1002)] + [observation(10)]
        limited = compare_event_trials(many, [0, len(many) - 1], window_ms=2000)
        self.assertIn('event_limit', limited['trials'][0]['quality_flags'])
        with self.assertRaises(ValueError):
            compare_event_trials([observation(0)] * 10001, [0, 1])

    def test_dialogue_and_map_anchors_compare_scopes_without_inferring_timers(self):
        from types import SimpleNamespace
        from tests.support.branches import conversation
        from reconstruction.comparison_anchors import comparison_rows
        from reconstruction.event_timer_export import build_timer_candidate
        store=SimpleNamespace(sessions=[],presentation_observations=[],map_arrival_anchors=[])
        for generation,time in enumerate((0,10,20),1):
            item=conversation(identifier=generation)
            item.npc.update(name='NPC',x=10,y=20,map_generation=generation)
            item.started=time
            for i,step in enumerate(item.steps):
                step.update(timestamp=time+i/10,packet_index=generation*100+i)
            store.sessions.append(item)
            own=observation(time+.2,9,context='during_dialogue',packet_index=generation*100+2)
            own['npc']['map_generation']=generation
            outside=observation(time+.8,7,packet_index=generation*100+20)
            outside['npc']['map_generation']=generation
            other=deepcopy(outside);other.update(actor_id=43,packet_index=generation*100+21)
            other['npc']['name']='Other'
            wrong=deepcopy(outside);wrong.update(flow_id='unrelated',packet_index=generation*100+22)
            store.presentation_observations.extend([own,outside,other,wrong])
            store.map_arrival_anchors.append(dict(kind='map_arrival',anchor_type='map_arrival',fields={},
                context='comparison_anchor',timestamp=time-.1,packet_index=generation*100-1,
                capture_session=0,flow_id='flow',actor_id=None,entity_kind='MAP',target_observed=False,
                connection='receive',npc=dict(map_name='test.gat',map_generation=generation)))
        original=deepcopy(store)
        for mode,count in (('dialogue_start',3),('map_arrival',3)):
            rows=comparison_rows(store,mode)
            anchors=[i for i,row in enumerate(rows) if row.get('anchor_type')==mode]
            result=compare_event_trials(rows,anchors,window_ms=2000)
            self.assertEqual(result['anchor_type'],mode)
            self.assertEqual(result['status'],'repeated_consistent')
            self.assertEqual(len(result['trials'][0]['events']),count)
            self.assertFalse(result['cause_confirmed'])
            self.assertFalse(result['server_timer_confirmed'])
            with self.assertRaises(ValueError):build_timer_candidate(result,0,[1,100,200],confirmed=True)
            import tempfile
            from pathlib import Path
            from storage.event_trial_selection import save_selection,load_selection
            from tests.unit.test_event_trial_selection import raw_log
            with tempfile.TemporaryDirectory() as folder:
                source=Path(folder)/'capture.jsonl';raw_log(source,'anchors')
                saved=Path(folder)/'anchors.json'
                save_selection(saved,rows,anchors,{0:str(source)},2000)
                remapped=deepcopy(rows)
                for row in remapped:
                    row['capture_session']=7
                    row['packet_index']+=10000
                self.assertEqual(load_selection(saved,remapped,{7:str(source)}),(anchors,2000))

        self.assertEqual(store.__dict__,original.__dict__)

    def test_review_matches_target_semantics_keeps_reports_and_bounds_excluded_details(self):
        from reconstruction.event_trials import trial_review
        def anchor(time,generation):
            return dict(kind='map_arrival',anchor_type='map_arrival',fields={},context='comparison_anchor',
                timestamp=time,packet_index=int(time*100),capture_session=0,flow_id='flow',
                actor_id=None,entity_kind='MAP',target_observed=False,
                npc=dict(map_name='test.gat',map_generation=generation))
        first=observation(.5,9)
        second=observation(10.5,9);second['npc'].update(name='Other',map_generation=2)
        waiting=observation(10.6,7,context='input_wait');waiting['npc']['map_generation']=2
        closing=observation(10.7,7,context='close_wait');closing['npc']['map_generation']=2
        unrelated=deepcopy(waiting);unrelated['flow_id']='other-flow'
        rows=[anchor(0,1),first,anchor(10,2),second,waiting,closing,unrelated,anchor(20,3)]
        report=compare_event_trials(rows,[0,2,7],window_ms=2000)
        before=deepcopy(report)
        review=trial_review(report,1,rows,max_details=1)
        self.assertEqual(review['differences'][1]['status'],'target_changed')
        self.assertEqual(review['excluded_counts'],{'input_wait':1,'close_wait':1})
        self.assertEqual(len(review['excluded']),1)
        self.assertEqual(review['omitted_details'],1)
        self.assertEqual(trial_review(report,2,rows)['differences'][1]['status'],'unobserved')
        self.assertEqual(report,before)

    def test_difference_exclusion_and_timer_role_labels_keep_codes_readable(self):
        from gui.event_trials import (
            difference_label, exclusion_label, timer_role_code, timer_role_label)

        self.assertEqual(difference_label('target_changed'), '対象が異なる（target_changed）')
        self.assertEqual(difference_label('same'), '内容一致（same）')
        self.assertEqual(difference_label('unknown_status'), 'unknown_status')
        self.assertEqual(exclusion_label('close_wait'), 'close応答待ち中（close_wait）')
        self.assertEqual(exclusion_label('target_different_map'),
                         '作用先が別MAP・別インスタンス（target_different_map）')
        self.assertEqual(exclusion_label('novel_reason'), 'novel_reason')
        self.assertEqual(timer_role_code('emotion'), 'command')
        self.assertEqual(timer_role_code('classchange'), 'command')
        self.assertEqual(timer_role_code('effect_value'), 'comment')
        self.assertEqual(timer_role_code('sound'), 'rejected')
        self.assertEqual(timer_role_code('music'), 'rejected')
        self.assertEqual(timer_role_code('viewpoint'), 'rejected')
        self.assertIsNone(timer_role_code(None))
        self.assertEqual(timer_role_label('unittalk'), '実行命令候補（command）')
        self.assertEqual(timer_role_label('classchange'), '実行命令候補（command）')
        self.assertEqual(timer_role_label('event_marker'), 'コメント採用のみ（comment）')
        self.assertEqual(timer_role_label('progressbar'), 'タイマー拒否（rejected）')
        self.assertEqual(timer_role_label(None), '—')
