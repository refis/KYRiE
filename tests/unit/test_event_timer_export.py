from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from reconstruction.event_timer_export import (build_timer_candidate, DEFAULT_PROFILE, load_timer_candidate,
                                                render_timer_text)
from tests.support.event_trials import repeated_report


class EventTimerExportTests(unittest.TestCase):
    def test_text_keeps_full_evidence_commented_and_only_regenerated_code_active(self):
        report = repeated_report('effect')
        report['source_sessions'] = {0: 'capture\ninitnpctimer;\n.jsonl', 10: 'other.jsonl'}
        before = deepcopy(report)
        document = build_timer_candidate(report, 0, [100, 1100], confirmed=True)
        text = render_timer_text(document, report, 0)
        evidence, code = text.split('\n', 1)
        self.assertTrue(evidence.startswith('// '))
        self.assertEqual(json.loads(evidence[3:]), json.loads(json.dumps(document)))
        self.assertEqual(code, document['auriga'])
        self.assertNotIn('\ninitnpctimer;', text)
        self.assertIn('OnTimer1100:', code)
        self.assertFalse(document['automatic_start_generated'])
        with self.assertRaises(ValueError):
            render_timer_text(dict(document, auriga='initnpctimer;'), report, 0)
        self.assertEqual(report, before)

    def test_saved_manual_timer_requires_same_report_trial_flags_and_generated_code(self):
        report = repeated_report('effect')
        original = deepcopy(report)
        document = build_timer_candidate(report, 0, [100, 1100], confirmed=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'timer.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertEqual(load_timer_candidate(path, report, 0), document)
            for key, value in (('trial_index', 1), ('automatic_start_generated', True),
                               ('adoption_confirmed', False), ('cause_confirmed', True),
                               ('auriga', 'initnpctimer;'), ('source_report', {}),
                               ('manual_times_ms', [False, 1100]), ('extra', 1)):
                with self.subTest(key=key):
                    path.write_text(json.dumps(dict(document, **{key: value})), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_timer_candidate(path, report, 0)
            for raw in ('{"manual_times_ms":[],"manual_times_ms":[]}', '{"time":NaN}'):
                path.write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_timer_candidate(path, report, 0)
        self.assertEqual(report, original)

    def test_manual_times_form_labels_without_inferred_start_or_overwriting_observations(self):
        report = repeated_report(); before = deepcopy(report)
        result = build_timer_candidate(report, 0, [100, 1100], confirmed=True)
        self.assertIn('OnTimer100:', result['auriga'])
        self.assertIn('OnTimer1100:', result['auriga'])
        self.assertIn('emotion 7;', result['auriga'])
        self.assertIn('emotion 9;', result['auriga'])
        self.assertNotIn('initnpctimer', result['auriga'])
        self.assertNotIn('OnInit:', result['auriga'])
        self.assertFalse(result['server_timer_confirmed'])
        self.assertFalse(result['automatic_start_generated'])
        self.assertEqual(result['source_report']['trials'][0]['events'][1]['offset_ms'], 1000)
        same = build_timer_candidate(report, 0, [100, 100], confirmed=True)['auriga']
        self.assertEqual(same.count('OnTimer100:'), 1)
        self.assertLess(same.index('emotion 7;'), same.index('emotion 9;'))
        self.assertEqual(same.count('end;'), 2)
        mixed = build_timer_candidate(repeated_report('effect'), 0, [100, 1100], confirmed=True)
        self.assertIn('misceffect 9;', mixed['auriga'])
        result['source_report']['trials'][0]['events'][0]['observation']['fields']['value'] = 99
        self.assertEqual(report, before)

    def test_confirmation_quality_manual_time_scope_and_template_invariants_are_required(self):
        report = repeated_report()
        with self.assertRaises(ValueError):
            build_timer_candidate(report, 0, [100, 1100])
        for times in ([], [0, 100], [True, 100], [100, 99], [1, 2147483648], ['100', 200]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                build_timer_candidate(report, 0, times, confirmed=True)
        for index in (-1, True, 99):
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_timer_candidate(report, index, [100, 1100], confirmed=True)
        changed = deepcopy(report); changed['trials'][0]['quality_flags'] = ['overlapping_windows']
        with self.assertRaises(ValueError):
            build_timer_candidate(changed, 0, [100, 1100], confirmed=True)
        for key, value in (('kind', 'sound'), ('actor_id', 99), ('target_observed', False), ('packet_index', None)):
            with self.subTest(key=key):
                changed = deepcopy(report); changed['trials'][0]['events'][1]['observation'][key] = value
                with self.assertRaises(ValueError):
                    build_timer_candidate(changed, 0, [100, 1100], confirmed=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'profile.json'
            for key, value in (('label', 'OnTimer0:'), ('header', 'initnpctimer;'),
                               ('emotion', 'emotion 0;'), ('effect', '{value.__class__}'), ('label_end', 'goto Loop;')):
                with self.subTest(key=key):
                    templates = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8')); templates[key] = value
                    path.write_text(json.dumps(templates), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        build_timer_candidate(report, 0, [100, 1100], confirmed=True, profile=path)

    def test_comparison_only_modes_and_owner_scoped_rows_cannot_be_adopted(self):
        report=repeated_report();before=deepcopy(report)
        for mode in ('dialogue_start','map_arrival','unknown',None):
            changed=deepcopy(report);changed['anchor_type']=mode
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                build_timer_candidate(changed,0,[100,1100],confirmed=True)
        changed=deepcopy(report);changed['include_dialogue_actions']=True
        with self.assertRaises(ValueError):build_timer_candidate(changed,0,[100,1100],confirmed=True)
        for where in ('anchor','event'):
            for marker,value in (('comparison_scope','dialogue_owner'),('anchor_type','dialogue_start')):
                changed=deepcopy(report)
                row=changed['trials'][0]['anchor'] if where=='anchor' else changed['trials'][0]['events'][1]['observation']
                row[marker]=value
                with self.subTest(where=where,marker=marker),self.assertRaises(ValueError):
                    build_timer_candidate(changed,0,[100,1100],confirmed=True)
        self.assertEqual(report,before)

    def test_recipient_context_and_unassigned_announcement_require_explicit_scope(self):
        from reconstruction.event_timer_export import validate_timer_trial
        report=repeated_report();before=deepcopy(report)
        changes=[{'actor_id':99},{'entity_kind':'MOB'},{'target_observed':False},
                 {'capture_session':8},{'flow_id':'other'}]
        changes += [{'context':value} for value in ('external_candidate','input_wait','close_wait','during_dialogue','outside_visibility','review_only')]
        for fields in changes:
            changed=deepcopy(report);changed['trials'][0]['events'][1]['observation'].update(fields)
            with self.subTest(fields=fields),self.assertRaises(ValueError):validate_timer_trial(changed,0)
        for kind in ('music','sound','viewpoint','progressbar','progress_action','status_action',
                     'script_command','npc_display_action','mapcell','dialogue_size'):
            changed=deepcopy(report);changed['trials'][0]['events'][1]['observation']['kind']=kind
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_timer_trial(changed,0)
        announcement=deepcopy(report);event=announcement['trials'][0]['events'][1]
        event['association_basis']='selected_timer_window_same_flow'
        event['observation'].update(kind='announcement',actor_id=None,target_observed=False,
            entity_kind='unresolved',npc={},fields={'text':'notice','broadcast_prefix':None})
        self.assertIn('announce "notice",0;',build_timer_candidate(announcement,0,[100,1100],confirmed=True)['auriga'])
        for key,value in (('context','input_wait'),('context','close_wait'),('flow_id','other'),('capture_session',9),
                          ('map_context',{'map_name':'other.gat','map_generation':1}),
                          ('map_context',{'map_name':'test.gat','map_generation':2})):
            changed=deepcopy(announcement);changed['trials'][0]['events'][1]['observation'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_timer_trial(changed,0)
        changed=deepcopy(announcement);changed['trials'][0]['events'][1].pop('association_basis')
        with self.assertRaises(ValueError):validate_timer_trial(changed,0)
        self.assertEqual(report,before)

    def test_self_unittalk_manual_export_preserves_text_and_rejects_unsafe_profile_or_target(self):
        report=repeated_report('unittalk')
        message='NPC";\nend;\\日本語'
        for trial in report['trials']:
            trial['events'][1]['observation']['fields']={'text':message}
        before=deepcopy(report)
        result=build_timer_candidate(report,0,[100,1100],confirmed=True)
        self.assertIn('unittalk '+json.dumps(message,ensure_ascii=False)+';',result['auriga'])
        self.assertNotIn('getnpcid',result['auriga'])
        self.assertEqual(result['source_report'],report)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'candidate.json';target.write_text(json.dumps(result),encoding='utf-8')
            self.assertEqual(load_timer_candidate(target,report,0),result)
            profile=Path(folder)/'profile.json'
            templates=json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
            templates.pop('unittalk');profile.write_text(json.dumps(templates),encoding='utf-8')
            self.assertEqual(build_timer_candidate(report,0,[100,1100],confirmed=True,profile=profile),result)
            for template in ('unittalk "changed";','unittalk {text};\nend;','unittalk getnpcid(0,"Other"),{text};'):
                templates['unittalk']=template;profile.write_text(json.dumps(templates),encoding='utf-8')
                with self.subTest(template=template),self.assertRaises(ValueError):
                    build_timer_candidate(report,0,[100,1100],confirmed=True,profile=profile)
        for fields in ({'text':None},{'text':'x'*65536},{'text':'hello','target':'Other'}):
            changed=deepcopy(report);changed['trials'][0]['events'][1]['observation']['fields']=fields
            with self.subTest(fields_type=type(fields.get('text'))),self.assertRaises(ValueError):
                build_timer_candidate(changed,0,[100,1100],confirmed=True)
        for change in ({'actor_id':99},{'context':'external_candidate'},{'entity_kind':'MOB'},{'target_observed':False}):
            changed=deepcopy(report);changed['trials'][0]['events'][1]['observation'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                build_timer_candidate(changed,0,[100,1100],confirmed=True)
        self.assertEqual(report,before)

    def test_overhead_and_comment_timer_kinds_are_manually_adoptable(self):
        report = repeated_report('overhead')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields'] = {'text': '頭上"}'}
        code = build_timer_candidate(report, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('showmessage ' + json.dumps('頭上"}', ensure_ascii=False) + ';', code)
        for kind, fields, needle in (
                ('effect_value', {'effect_id': 7, 'value': 9}, 'effect=7, value=9'),
                ('event_marker', {'x': 1, 'y': 2, 'state': 3, 'kind': 4}, 'state=3, kind=4, x=1, y=2')):
            with self.subTest(kind=kind):
                sample = repeated_report(kind)
                for trial in sample['trials']:
                    trial['events'][1]['observation']['fields'] = fields
                text = build_timer_candidate(sample, 0, [100, 1100], confirmed=True)['auriga']
                self.assertIn(needle, text)
                self.assertTrue(any(line.lstrip().startswith('//') and needle in line
                                    for line in text.splitlines()))

    def test_classchange_timer_emits_setnpcdisplay_for_identity_npc(self):
        from pathlib import Path
        import tempfile
        report = repeated_report('classchange')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields'] = {'class_id': 1002, 'kind': 1}
        code = build_timer_candidate(report, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('setnpcdisplay "NPC",1002;', code)
        self.assertFalse(any(line.lstrip().startswith('//') and 'setnpcdisplay' in line
                             for line in code.splitlines()))
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'event_timers.json'
            templates = json.loads(Path('config/auriga/event_timers.json').read_text(encoding='utf-8'))
            for bad in ('setnpcdisplay "Other",1002;', 'setnpcdisplay "NPC",999;',
                        '// setnpcdisplay {target},{class_id};'):
                templates['classchange'] = bad
                profile.write_text(json.dumps(templates), encoding='utf-8')
                with self.subTest(template=bad), self.assertRaises(ValueError):
                    build_timer_candidate(report, 0, [100, 1100], confirmed=True, profile=profile)
        oversized = deepcopy(report)
        oversized['trials'][0]['events'][1]['observation']['fields'] = {'class_id': 70000, 'kind': 1}
        with self.assertRaises(ValueError):
            build_timer_candidate(oversized, 0, [100, 1100], confirmed=True)

    def test_visibility_action_timer_allows_cloak_anywhere_and_hide_on_instance_only(self):
        from pathlib import Path
        import tempfile
        cloak = repeated_report('visibility_action')
        for trial in cloak['trials']:
            trial['events'][1]['observation']['fields'] = dict(
                commands=['cloakonnpc'], target=None, options=4, previous_options=0)
        cloak_code = build_timer_candidate(cloak, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('cloakonnpc;', cloak_code)
        self.assertNotIn('hideonnpc;', cloak_code)

        instance = repeated_report('visibility_action')
        for trial in instance['trials']:
            trial['anchor']['npc'] = dict(trial['anchor']['npc'], map_name='1@toy.gat')
            for event in trial['events']:
                event['observation']['npc'] = dict(event['observation']['npc'], map_name='1@toy.gat')
            trial['events'][1]['observation']['fields'] = dict(
                commands=['hideonnpc', 'cloakoffnpc'], target=None, options=2, previous_options=4)
        instance['npc_identity'] = dict(instance['npc_identity'], map_name='1@toy.gat')
        code = build_timer_candidate(instance, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('hideonnpc;', code)
        self.assertIn('cloakoffnpc;', code)
        self.assertFalse(any(line.lstrip().startswith('//') and 'hideonnpc' in line
                             for line in code.splitlines()))

        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'event_timers.json'
            templates = json.loads(Path('config/auriga/event_timers.json').read_text(encoding='utf-8'))
            for bad in ('hideonnpc "Other";', '// {command};', 'emotion 1;'):
                templates['visibility_action'] = bad
                profile.write_text(json.dumps(templates), encoding='utf-8')
                with self.subTest(template=bad), self.assertRaises(ValueError):
                    build_timer_candidate(instance, 0, [100, 1100], confirmed=True, profile=profile)

        non_instance_hide = repeated_report('visibility_action')
        for trial in non_instance_hide['trials']:
            trial['events'][1]['observation']['fields'] = dict(
                commands=['hideonnpc'], target=None, options=2, previous_options=0)
        with self.assertRaises(ValueError):
            build_timer_candidate(non_instance_hide, 0, [100, 1100], confirmed=True)

        targeted = deepcopy(instance)
        targeted['trials'][0]['events'][1]['observation']['fields'] = dict(
            commands=['cloakonnpc'], target=dict(name='Other', map_name='1@toy.gat'),
            options=4, previous_options=0)
        with self.assertRaises(ValueError):
            build_timer_candidate(targeted, 0, [100, 1100], confirmed=True)
        invalid = deepcopy(cloak)
        invalid['trials'][0]['events'][1]['observation']['fields'] = dict(
            commands=['viewpoint'], target=None, options=0, previous_options=None)
        with self.assertRaises(ValueError):
            build_timer_candidate(invalid, 0, [100, 1100], confirmed=True)

    def test_unittalk_audit_is_preliminary_bounded_and_keeps_source_reasons(self):
        from tools.audit_event_trial_review import review_unittalk
        from tests.support.event_trials import observation
        rows=[observation(1,kind='unittalk',fields={'text':'hello'}),
              observation(2,kind='unittalk',fields={'text':'wait'},context='close_wait'),
              observation(3,kind='unittalk',fields={'text':'mob'},entity_kind='MOB'),
              observation(4,kind='unittalk',fields={'text':'unknown'},entity_kind='unresolved',target_observed=False,npc={}),
              observation(5)]
        original=deepcopy(rows)
        result=review_unittalk(rows,max_details=2)
        self.assertEqual(result['count'],4)
        self.assertEqual(result['preliminary_anchor_candidates'],1)
        self.assertEqual(result['exclusion_reason_counts']['context_close_wait'],1)
        self.assertEqual(result['exclusion_reason_counts']['not_npc'],2)
        self.assertEqual(result['omitted_details'],2)
        self.assertEqual(result['details'][0]['packet_index'],100)
        self.assertTrue(result['preliminary_only'])
        self.assertFalse(result['manual_adoption_performed'])
        self.assertEqual(rows,original)
        for limit in (0,True,1001):
            with self.assertRaises(ValueError):review_unittalk(rows,limit)
