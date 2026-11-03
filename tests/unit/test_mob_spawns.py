import struct
import unittest
import json
from pathlib import Path
import tempfile
from dataclasses import replace
from copy import deepcopy

from reconstruction.world import WorldStore
from reconstruction.mob_spawns import MobSpawnStore
from reconstruction.mob_spawn_export import (build_candidates, render_candidates, DEFAULT_PROFILE,
    configure_candidate, CONFIGURED_PROFILE, load_configured, validate_configured, render_configured,
    format_observation_evidence)
from tests.support.skills import mob
from tests.support.world import packet, map_packet, actor_packet


class MobSpawnTests(unittest.TestCase):
    def test_configured_placement_resume_and_text_validate_full_evidence(self):
        self.apply(mob(42))
        candidate = build_candidates(self.store.snapshot())['candidates'][0]
        original = deepcopy(candidate)
        sources = {0: 'capture\nnot-a-command.jsonl'}
        fields = dict(map_name='prontera', x=150, y=200, xs=0, ys=0, mob_name='テストMOB',
                      class_id=1005, amount=1, delay1=5000, delay2=0, event='')
        document = configure_candidate(candidate, fields, confirmed=True, source_sessions=sources)
        normalized = json.loads(json.dumps(document))
        self.assertEqual(validate_configured(normalized, candidate, sources), document)
        text = render_configured(document, candidate, sources)
        self.assertEqual([row for row in text.splitlines() if not row.startswith('//')],
                         [document['placement_row']])
        self.assertIn('observation', text)
        self.assertIn('capture\\nnot-a-command', text)
        for key, value in [('placement_row', 'malicious'), ('review_header', '// changed'),
                           ('configured_values_confirmed', False), ('schema_version', True),
                           ('source_sessions', {}), ('observation', {})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_configured(dict(normalized, **{key: value}), candidate, sources)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'configured.json'
            path.write_text(json.dumps(normalized), encoding='utf-8')
            self.assertEqual(load_configured(path, candidate, sources), document)
            for raw in ('{"schema_version":1,"schema_version":1}', '{"value":NaN}'):
                path.write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_configured(path, candidate, sources)
        self.assertEqual(candidate, original)

    def test_manual_placement_validates_all_settings_and_preserves_observations(self):
        self.apply(mob(42))
        candidate = build_candidates(self.store.snapshot())['candidates'][0]
        original = json.dumps(candidate, sort_keys=True)
        fields = dict(map_name='prontera', x=150, y=200, xs=0, ys=0, mob_name='テストMOB',
                      class_id=1005, amount=1, delay1=5000, delay2=0, event='')
        document = configure_candidate(candidate, fields, confirmed=True, source_sessions={0: 'capture.jsonl'})
        self.assertEqual(document['placement_row'], 'prontera,150,200,0,0\tmonster\tテストMOB\t1005,1,5000,0,')
        self.assertTrue(document['active_placement_generated'])
        self.assertIsNone(document['observation']['placement_fields']['amount'])
        self.assertIsNone(document['observation']['placement_fields']['x'])
        self.assertEqual(document['setting_origin'], 'manual_review')
        with self.assertRaises(ValueError):
            configure_candidate(candidate, fields)
        for key, value in [('map_name', 'a,b'), ('map_name', 'x' * 24), ('x', ''), ('x', -1),
                           ('y', 1024), ('xs', True), ('class_id', 0), ('amount', 0),
                           ('amount', 1001), ('delay1', 2147483648), ('delay2', -1),
                           ('mob_name', 'a\nmonster'), ('mob_name', 'a//comment'),
                           ('mob_name', 'あ' * 12), ('mob_name', '😀'), ('event', 'label'),
                           ('event', 'NPC::OnDead\nend'), ('event', None)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                configure_candidate(candidate, dict(fields, **{key: value}), confirmed=True)
        with self.assertRaises(ValueError):
            configure_candidate(candidate, dict(fields, delay1=2147483647, delay2=1), confirmed=True)
        configured = configure_candidate(candidate, dict(fields, event='Npc_1::OnMobDead'), confirmed=True)
        self.assertTrue(configured['placement_row'].endswith('Npc_1::OnMobDead'))
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'unsafe.json'
            templates = json.loads(CONFIGURED_PROFILE.read_text(encoding='utf-8'))
            templates['placement'] += '\nmonster'
            profile.write_text(json.dumps(templates), encoding='utf-8')
            with self.assertRaises(ValueError):
                configure_candidate(candidate, fields, confirmed=True, profile=profile)
        document['observation']['requires_edit'].clear()
        self.assertEqual(json.dumps(candidate, sort_keys=True), original)

    def test_placement_candidates_preserve_scopes_and_leave_configuration_unknown(self):
        self.apply(map_packet(timestamp=0))
        self.apply(mob(42, timestamp=1))
        self.apply(packet(0x80, struct.pack('<IB', 42, 1), timestamp=2))
        self.apply(mob(42, timestamp=7))
        self.apply(map_packet(name='other.gat', timestamp=8))
        self.apply(mob(42, timestamp=9))
        self.apply(mob(42, timestamp=10), session=1)
        before = self.store.snapshot()
        report = build_candidates(before, {0: 'first.jsonl', 1: 'second.jsonl'})
        self.assertEqual(len(report['candidates']), 3)
        first = report['candidates'][0]
        self.assertEqual(len(first['appearances']), 2)
        self.assertEqual(first['observed']['intervals'][0]['duration_ms'], 5000)
        self.assertEqual(first['placement_fields']['class_id'], 1005)
        self.assertEqual(first['placement_fields']['map_name'], 'prontera.gat')
        for candidate in report['candidates']:
            for key in ('x', 'y', 'xs', 'ys', 'mob_name', 'amount', 'delay1', 'delay2', 'event'):
                self.assertIsNone(candidate['placement_fields'][key])
                self.assertIn(key, candidate['requires_edit'])
        self.assertIsNone(report['candidates'][-1]['placement_fields']['map_name'])
        self.assertFalse(report['active_placements_generated'])
        before_first = deepcopy(first)
        evidence = format_observation_evidence(first)
        self.assertEqual(first, before_first)
        self.assertIn('自動代入はしません', evidence)
        self.assertIn('amountへは使いません', evidence)
        self.assertIn('delay1/delay2へは使いません', evidence)
        self.assertIn('5000ms', evidence)
        self.assertIn('(150,200)', evidence)
        self.assertIn('要編集列:', evidence)
        with self.assertRaises(ValueError):
            format_observation_evidence({})
        with self.assertRaises(ValueError):
            format_observation_evidence(None)
        report['source_sessions'][0] = 'evil\nmonster\tdeclaration'
        text = render_candidates(report)
        self.assertTrue(all(line.startswith('//') for line in text.splitlines()))
        self.assertIn('prontera.gat,?,?,?,?\tmonster\t?\t1005,?,?,?,?', text)
        self.assertIn('evil\\nmonster\\tdeclaration', text)
        self.assertEqual(self.store.snapshot(), before)
        first['appearances'][0]['first_position']['x'] = -1
        self.assertEqual(self.store.snapshot(), before)
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'unsafe.json'
            templates = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
            templates['candidate'] = '{class_id},active'
            profile.write_text(json.dumps(templates), encoding='utf-8')
            with self.assertRaises(ValueError):
                render_candidates(report, profile)

    def setUp(self):
        self.world = WorldStore()
        self.store = MobSpawnStore(self.world)
        self.index = 0

    def apply(self, event, session=0):
        self.world.apply(event, session, self.index)
        self.store.apply(event, session, self.index)
        self.index += 1

    def test_visibility_peak_and_reobservation_do_not_become_spawn_settings(self):
        self.apply(map_packet(timestamp=0))
        self.apply(mob(42, timestamp=1))
        self.apply(mob(43, timestamp=2))
        moving = actor_packet(actor_id=42, actor_type=5, pid=0x9fd, x=160, y=210)
        raw = bytearray(moving.raw)
        struct.pack_into('<H', raw, 23, 1005)
        self.apply(replace(moving, timestamp=3, raw=bytes(raw)))
        self.apply(packet(0x80, struct.pack('<IB', 42, 1), timestamp=5))
        self.apply(packet(0x80, struct.pack('<IB', 43, 0), timestamp=6))
        self.apply(mob(42, timestamp=10))
        self.apply(mob(43, timestamp=15))
        result = self.store.snapshot()
        group = result['groups'][0]
        self.assertEqual((group['appearances'], group['unique_actor_ids'], group['peak_tracked']), (4, 2, 2))
        self.assertEqual((group['deaths'], group['removals']), (1, 1))
        self.assertEqual([row['duration_ms'] for row in group['intervals']], [5000, 9000])
        self.assertTrue(all(not row['configured_respawn_confirmed'] for row in group['intervals']))
        self.assertIsNone(group['configured_spawn_count'])
        self.assertIsNone(group['configured_respawn_ms'])
        self.assertEqual(result['appearances'][0]['first_position'], dict(x=150, y=200))
        result['appearances'][0]['first_position']['x'] = -1
        self.assertNotEqual(self.store.records[0]['first_position']['x'], -1)

    def test_scope_replacement_invalid_time_and_limits_do_not_join_lifetimes(self):
        self.apply(mob(42, timestamp=1))
        self.apply(packet(0x80, struct.pack('<IB', 42, 1), timestamp=0))
        self.apply(mob(42, timestamp=2))
        self.assertIsNone(self.store.records[-1]['reobservation_interval'])
        self.apply(map_packet(timestamp=3))
        self.apply(mob(42, timestamp=4))
        self.assertIsNone(self.store.records[-1]['reobservation_interval'])
        self.apply(actor_packet(actor_id=42, actor_type=6, timestamp=5))
        self.assertEqual(self.store.records[-1]['end']['kind'], 'appearance_or_class_changed')
        self.apply(mob(42, timestamp=6), session=1)
        self.assertIsNone(self.store.records[-1]['reobservation_interval'])
        self.store.max_records = len(self.store.records)
        self.apply(mob(99, timestamp=7), session=1)
        self.assertTrue(self.store.saturated)

    def test_grouped_mob_exports_follow_server_then_lowest_observed_actor(self):
        from reconstruction.mob_spawn_export import build_candidates
        for ip,aid,cls in (('10.0.0.10',1,1005),('10.0.0.2',20,1005),('10.0.0.2',10,2000)):
            connection=str((ip,5121,'192.0.2.1',50000))
            event=actor_packet(actor_id=aid,actor_type=5,connection=connection)
            raw=bytearray(event.raw);struct.pack_into('<H',raw,23,cls)
            self.apply(replace(event,raw=bytes(raw)))
        report=self.store.snapshot()
        self.assertEqual([r['actor_id'] for r in report['appearances']],[10,20,1])
        self.assertEqual([r['class_id'] for r in report['groups']],[2000,1005,1005])
        candidates=build_candidates(report)['candidates']
        self.assertEqual([r['appearances'][0]['actor_id'] for r in candidates],[10,20,1])
