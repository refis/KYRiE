import json
from pathlib import Path
import tempfile
import unittest

from reconstruction.world import WorldStore
from reconstruction.skills import SkillStore
from reconstruction.mob_skill_export import (build_candidates, render_candidates, DEFAULT_PROFILE,
    COLUMNS, configure_candidate, STATUS_CONDITIONS, STATUS_VALUES, NUMERIC_CONDITIONS,
    load_configured, MAX_CONFIGURED_BYTES, render_configured, valid_val_token,
    format_observation_evidence)
from tests.support.skills import mob, damage, cast


class MobSkillExportTests(unittest.TestCase):
    def test_lua_priority_names_reach_candidates_without_changing_packet_skill_id(self):
        from copy import deepcopy
        from reconstruction.skills import load_skill_names
        world=WorldStore();skills=SkillStore(world)
        for event in (mob(),damage(skill=383)):
            world.apply(event)
            skills.apply(event)
        snapshot=skills.snapshot();before=deepcopy(snapshot)
        names=load_skill_names()
        self.assertEqual(names[383],'ウィンドウォーク')
        self.assertEqual(names[390],'リジェクトソード')
        candidate=build_candidates(snapshot,names)['candidates'][0]
        self.assertTrue(candidate['db_fields']['NAME'].endswith('＠ウィンドウォーク'))
        self.assertEqual(candidate['db_fields']['SKILL_ID'],383)
        self.assertEqual(snapshot,before)

    def test_name_uses_observed_monster_and_skill_names_and_supports_japanese_rows(self):
        from copy import deepcopy
        snapshot=self.observed([3]).snapshot()
        for row in snapshot['observations']:row['name']='ポリン'
        before=deepcopy(snapshot)
        candidate=build_candidates(snapshot,{177:'ブラインドアタック'})['candidates'][0]
        self.assertEqual(candidate['db_fields']['NAME'],'ポリン＠ブラインドアタック')
        self.assertEqual(snapshot,before)
        unknown=build_candidates(snapshot)['candidates'][0]
        self.assertEqual(unknown['db_fields']['NAME'],'ポリン＠SKILL_ID_177')
        changed=deepcopy(snapshot);changed['observations'][0]['name']='別名'
        changed['observations'].append(dict(changed['observations'][0],name='ポリン'))
        self.assertEqual(build_candidates(changed,{177:'スキル'})['candidates'][0]['db_fields']['NAME'],'MOB_ID_1005＠スキル')
        fields=dict.fromkeys(COLUMNS,0)
        fields.update(MOB_ID=1005,NAME=candidate['db_fields']['NAME'],STATE='attack',SKILL_ID=177,
            SKILL_LV=3,RATE=1000,CANCEL='no',TARGET='target',CONDITION='always')
        document=configure_candidate(candidate,fields,confirmed=True)
        self.assertIn(',ポリン＠ブラインドアタック,',document['db_row'])
        self.assertEqual(len(document['db_row'].split(',')),19)
        self.assertIn(document['db_row'],render_configured(document))
        for name in ('ポリン,スキル','ポリン\nスキル','ポリン\x00スキル','clear'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                configure_candidate(candidate,dict(fields,NAME=name),confirmed=True)
        with tempfile.TemporaryDirectory() as folder:
            profile=Path(folder)/'style.json'
            style=json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'));style['name']='{monster_name}@{skill_name}'
            profile.write_text(json.dumps(style),encoding='utf-8')
            self.assertEqual(build_candidates(snapshot,{177:'スキル'},profile=profile)['candidates'][0]['db_fields']['NAME'],'ポリン@スキル')

    def test_legacy_observation_label_can_resume_without_rewriting_manual_name(self):
        from copy import deepcopy
        candidate=build_candidates(self.observed([3]).snapshot(),{177:'スキル'})['candidates'][0]
        old=deepcopy(candidate);old['db_fields']['NAME']='observed_1005_177'
        fields=dict.fromkeys(COLUMNS,0)
        fields.update(MOB_ID=1005,NAME='確認済み旧名',STATE='attack',SKILL_ID=177,
            SKILL_LV=3,RATE=1000,CANCEL='no',TARGET='target',CONDITION='always')
        document=configure_candidate(old,fields,confirmed=True)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'saved.json';path.write_text(json.dumps(document),encoding='utf-8')
            loaded=load_configured(path,candidate)
            self.assertEqual(loaded['db_fields']['NAME'],'確認済み旧名')
            self.assertEqual(loaded['observation'],candidate)
            changed=deepcopy(candidate);changed['observed']['known_levels']=[7]
            with self.assertRaises(ValueError):load_configured(path,changed)

    def test_configured_settings_resume_only_matching_valid_evidence(self):
        candidate = build_candidates(self.observed([65535]).snapshot())['candidates'][0]
        fields = dict.fromkeys(COLUMNS, 0)
        fields.update(MOB_ID=1005, NAME='resume_test', STATE='attack', SKILL_ID=177,
                      SKILL_LV=5, RATE=1000, CANCEL='no', TARGET='target', CONDITION='always')
        sources = {0: 'capture.jsonl'}
        document = configure_candidate(candidate, fields, confirmed=True, source_sessions=sources)
        original = json.dumps(candidate, sort_keys=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'configured.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertEqual(load_configured(path, candidate, sources), document)
            legacy = dict(document, db_row=','.join(str(document['db_fields'][key]) for key in COLUMNS))
            path.write_text(json.dumps(legacy), encoding='utf-8')
            self.assertEqual(load_configured(path, candidate, sources)['db_row'].split(',')[-1], '00')
            with self.assertRaises(ValueError):
                load_configured(path, candidate, {0: 'other.jsonl'})
            different = json.loads(json.dumps(candidate))
            different['skill_id'] = 99
            with self.assertRaises(ValueError):
                load_configured(path, different, sources)
            for key, value in [('schema_version', True), ('schema_version', 2),
                               ('db_row', '1005,wrong'), ('configured_values_confirmed', False),
                               ('setting_origin', 'automatic'), ('db_fields', {}),
                               ('observation', None), ('source_sessions', []), ('extra', 1)]:
                with self.subTest(key=key):
                    path.write_text(json.dumps(dict(document, **{key: value})), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_configured(path, candidate, sources)
            for raw in (b'[]', b'{', b'\xff', b'{"x":1,"x":2}', b'{"x":NaN}',
                        b'[' * 2000, b' ' * (MAX_CONFIGURED_BYTES + 1)):
                with self.subTest(size=len(raw)):
                    path.write_bytes(raw)
                    with self.assertRaises(ValueError):
                        load_configured(path, candidate, sources)
        self.assertEqual(json.dumps(candidate, sort_keys=True), original)

    def test_configured_db_text_has_one_valid_row_and_recoverable_bounded_evidence(self):
        candidate = build_candidates(self.observed([65535]).snapshot())['candidates'][0]
        candidate['skill_name'] = '日本語\n1005,not_a_row'
        fields = dict.fromkeys(COLUMNS, 0)
        fields.update(MOB_ID=1005, NAME='text_export', STATE='attack', SKILL_ID=177,
                      SKILL_LV=5, RATE=1000, CANCEL='no', TARGET='target', CONDITION='always')
        for emotion in (0, 9, 10, -123):
            with self.subTest(emotion=emotion):
                document = configure_candidate(candidate, dict(fields, EMOTION=emotion), confirmed=True,
                                               source_sessions={0: '日本語/capture.jsonl'})
                text = render_configured(document)
                lines = text.splitlines()
                active = [line for line in lines if not line.startswith('//')]
                self.assertEqual(active, [document['db_row']])
                self.assertEqual(int(active[0].split(',')[-1]), emotion)
                self.assertGreater(len(active[0].split(',')[-1]), 1)
                self.assertTrue(all(len(line.encode('utf-8')) < 1024 for line in lines))
                start = next(i for i, line in enumerate(lines) if line.startswith('// {"schema_version"'))
                recovered = json.loads(''.join(line[3:] for line in lines[start:]))
                self.assertEqual(recovered['observation'], json.loads(json.dumps(candidate)))
                self.assertEqual(recovered['source_sessions'], {'0': '日本語/capture.jsonl'})
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'profile.json'
            for value in ('1005,active_row', '// ' + 'x' * 901, '// bad\rline'):
                with self.subTest(value=value[:20]):
                    profile.write_text(json.dumps(dict(header=value, evidence_header='// evidence')), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        render_configured(document, profile)
        for bad in (dict(document, db_row='bad'), dict(document, configured_values_confirmed=False)):
            with self.assertRaises(ValueError):
                render_configured(bad)

    def test_manual_settings_require_complete_confirmed_safe_values(self):
        candidate = build_candidates(self.observed([65535]).snapshot())['candidates'][0]
        original = json.dumps(candidate, sort_keys=True)
        fields = dict.fromkeys(COLUMNS, 0)
        fields.update(MOB_ID=1005, NAME='reviewed_example', STATE='attack', SKILL_ID=177,
                      SKILL_LV=5, RATE=1000, CASTTIME=500, DELAY=6000, CANCEL='yes',
                      TARGET='target', CONDITION='always')
        document = configure_candidate(candidate, fields, confirmed=True, source_sessions={0: 'capture.jsonl'})
        self.assertEqual(len(document['db_row'].split(',')), 19)
        self.assertEqual(document['db_fields']['DELAY'], 6000)
        self.assertEqual(document['setting_origin'], 'manual_review')
        self.assertIsNone(document['observation']['db_fields']['DELAY'])
        self.assertEqual(json.dumps(candidate, sort_keys=True), original)
        document['observation']['requires_edit'].clear()
        self.assertTrue(candidate['requires_edit'])
        with self.assertRaises(ValueError):
            configure_candidate(candidate, fields)
        for key, value in [('NAME', 'clear'), ('NAME', 'a,//b'), ('NAME', 'a\nb'),
                           ('STATE', 'attack/chase'), ('CONDITION', 'unknown_condition'),
                           ('CONDITION_VALUE', 1), ('RATE', 10001), ('DELAY', -1),
                           ('VAL1', True), ('SKILL_LV', ''), ('MOB_ID', 0),
                           ('EMOTION', 2147483648), ('CANCEL', 'maybe')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                configure_candidate(candidate, dict(fields, **{key: value}), confirmed=True)
        for condition in NUMERIC_CONDITIONS:
            with self.subTest(condition=condition):
                configured = dict(fields, CONDITION=condition,
                                  CONDITION_VALUE=0 if condition == 'always' else 50)
                self.assertEqual(configure_candidate(candidate, configured, confirmed=True)
                                 ['db_fields']['CONDITION'], condition)
                for invalid in ('poison', -32769, 32768):
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        configure_candidate(candidate, dict(configured, CONDITION_VALUE=invalid), confirmed=True)
        for condition in STATUS_CONDITIONS:
            for value in STATUS_VALUES:
                with self.subTest(condition=condition, value=value):
                    configured = configure_candidate(candidate, dict(fields, CONDITION=condition,
                        CONDITION_VALUE=value), confirmed=True)
                    self.assertEqual(configured['db_row'].split(',')[11], value)
            for invalid in (0, -1, 'unknown', 'poison\n'):
                with self.subTest(condition=condition, invalid=invalid), self.assertRaises(ValueError):
                    configure_candidate(candidate, dict(fields, CONDITION=condition,
                        CONDITION_VALUE=invalid), confirmed=True)
        for boundary in (-32768, 32767):
            with self.subTest(boundary=boundary):
                self.assertEqual(configure_candidate(candidate, dict(fields,
                    CONDITION='skillused', CONDITION_VALUE=boundary), confirmed=True)
                    ['db_fields']['CONDITION_VALUE'], boundary)
        del fields['VAL6']
        with self.assertRaises(ValueError):
            configure_candidate(candidate, fields, confirmed=True)

    def test_string_val_tokens_are_explicit_and_keep_integers(self):
        candidate = build_candidates(self.observed([65535]).snapshot())['candidates'][0]
        original = json.dumps(candidate, sort_keys=True)
        fields = dict.fromkeys(COLUMNS, 0)
        fields.update(MOB_ID=1005, NAME='val_token', STATE='attack', SKILL_ID=177,
                      SKILL_LV=5, RATE=1000, CANCEL='no', TARGET='target', CONDITION='always',
                      VAL1='SC_STONE', VAL2=-3, VAL3='skill_name', VAL4=0)
        document = configure_candidate(candidate, fields, confirmed=True)
        self.assertEqual(document['db_fields']['VAL1'], 'SC_STONE')
        self.assertEqual(document['db_fields']['VAL2'], -3)
        self.assertEqual(document['db_fields']['VAL3'], 'skill_name')
        self.assertEqual(document['db_row'].split(',')[12:16], ['SC_STONE', '-3', 'skill_name', '0'])
        self.assertIsNone(document['observation']['db_fields']['VAL1'])
        self.assertTrue(valid_val_token('SC_STONE'))
        for invalid in ('', ' spaced', 'a b', 'a,b', 'a//b', 'x' * 65, 'line\nbreak', True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError) as raised:
                configure_candidate(candidate, dict(fields, VAL1=invalid), confirmed=True)
            self.assertNotIn('整数を入力してください', str(raised.exception))
        with self.assertRaises(ValueError) as emotion:
            configure_candidate(candidate, dict(fields, EMOTION='SC_STONE'), confirmed=True)
        self.assertIn('整数を入力してください', str(emotion.exception))
        self.assertEqual(json.dumps(candidate, sort_keys=True), original)

    def observed(self, levels):
        world = WorldStore()
        skills = SkillStore(world)
        events = [mob(42), mob(43), cast(42)]
        for i, level in enumerate(levels):
            events.append(damage(42, level=level, tick=1000 + i * 5000, timestamp=1 + i * 5))
        events.append(damage(43, level=levels[0], tick=1100, timestamp=1.1))
        for index, event in enumerate(events):
            world.apply(event, packet_index=index)
            skills.apply(event, packet_index=index)
        return skills

    def test_observation_evidence_text_is_advisory_and_does_not_mutate_candidate(self):
        from copy import deepcopy
        skills = self.observed([65535, 65535])
        candidate = build_candidates(skills.snapshot(), {177: 'blind'})['candidates'][0]
        before = deepcopy(candidate)
        text = format_observation_evidence(candidate)
        self.assertEqual(candidate, before)
        self.assertIn('自動代入はしません', text)
        self.assertIn('CASTTIMEへは使いません', text)
        self.assertIn('DELAYへは使いません', text)
        self.assertIn('cancel通知≠CANCEL=yes', text)
        self.assertIn('server_tick_damage', text)
        self.assertIn('詠唱通知ms: [500]', text)
        self.assertIn('要編集列:', text)
        self.assertIn('CASTTIME', text)
        for key in ('STATE', 'RATE', 'CASTTIME', 'DELAY', 'CANCEL'):
            self.assertIsNone(candidate['db_fields'][key])
        with self.assertRaises(ValueError):
            format_observation_evidence({})
        with self.assertRaises(ValueError):
            format_observation_evidence(None)

    def test_unknown_values_are_not_replaced_by_counts_or_observed_intervals(self):
        skills = self.observed([65535, 65535])
        report = build_candidates(skills.snapshot(), {177: 'blind'}, {0: 'capture.jsonl'})
        candidate = report['candidates'][0]
        self.assertEqual(len(candidate['individuals']), 2)
        fields = candidate['db_fields']
        for key in ('SKILL_LV', 'STATE', 'RATE', 'CASTTIME', 'DELAY', 'CANCEL', 'TARGET', 'CONDITION'):
            self.assertIsNone(fields[key])
        self.assertEqual(candidate['observed']['intervals']['server_tick_damage']['min_ms'], 5000)
        self.assertEqual(candidate['observed']['cast_ms'], [500])
        text = render_candidates(report)
        self.assertTrue(all(line.startswith('//') for line in text.splitlines()))
        row = next(line[3:] for line in text.splitlines() if line.startswith('// 1005,'))
        self.assertEqual(len(row.split(',')), len(COLUMNS))
        self.assertEqual(row.split(',')[7], '?')
        self.assertFalse(report['active_db_rows_generated'])
        candidate['individuals'][0]['known_levels'].append(99)
        self.assertNotIn(99, skills.summaries()[0]['known_levels'])

    def test_levels_conflicts_and_comment_only_profile_are_preserved(self):
        for levels, expected in (([5, 5], 5), ([5, 7], None), ([5, 65535], None)):
            with self.subTest(levels=levels):
                report = build_candidates(self.observed(levels).snapshot())
                self.assertEqual(report['candidates'][0]['db_fields']['SKILL_LV'], expected)
        with tempfile.TemporaryDirectory() as folder:
            document = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
            document['candidate'] = '{row}'
            path = Path(folder) / 'unsafe.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(ValueError):
                render_candidates(report, path)
