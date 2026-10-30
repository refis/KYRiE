from tests.support.skills import mob, damage, cast
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest

from reconstruction.skills import SkillStore, load_skill_names
from reconstruction.world import WorldStore
from storage.session_log import SessionLog
from tools.analyze_skills import analyze
from tests.support.world import actor_packet, map_packet, packet








class SkillTests(unittest.TestCase):
    def test_cast_tracking_end_reasons_preserve_actual_observation_references(self):
        from reconstruction.cast_review import build_cast_review
        for kind in ('removed', 'decode_error', 'capacity_reached', 'superseded', 'capture_changed'):
            with self.subTest(kind=kind):
                self.setUp()
                self.apply(mob())
                self.apply(cast())
                first = self.skills.events[0]
                if kind == 'removed':
                    self.apply(packet(0x80, struct.pack('<IB', 42, 0), timestamp=2))
                elif kind == 'decode_error':
                    self.apply(packet(0x1de, b'bad', timestamp=2))
                elif kind == 'capacity_reached':
                    self.skills.max_events = 1
                    self.apply(packet(0x1b9, struct.pack('<I', 42), timestamp=2))
                    self.assertNotEqual(first['cast_outcome'], 'cancelled')
                    self.assertEqual(len(self.skills.events), 1)
                elif kind == 'superseded':
                    self.apply(cast(timestamp=2))
                else:
                    self.skills.begin_capture(1)
                end = first['tracking_end']
                self.assertEqual(end['reason'], kind)
                row = build_cast_review(self.skills.events)[0]
                self.assertIsNone(row['packet_index'])
                if kind == 'capture_changed':
                    self.assertEqual(end['next_capture_session'], 1)
                    self.assertNotIn('packet_index', end)
                else:
                    self.assertEqual(end['packet_index'], 2)
                self.assertFalse(row['association_confirmed'])

    def test_cast_review_uses_only_existing_same_scope_links_and_keeps_pending_casts(self):
        from copy import deepcopy
        from reconstruction.cast_review import build_cast_review
        self.apply(mob(42))
        self.apply(mob(43))
        self.apply(cast(actor=42, timestamp=1))
        self.apply(cast(actor=43, timestamp=1.1))
        self.apply(damage(actor=42, timestamp=1.5))
        self.apply(packet(0x1b9, struct.pack('<I', 43), timestamp=1.6))
        self.apply(cast(actor=42, timestamp=3))
        observations = deepcopy(self.skills.events)
        original = deepcopy(observations)
        rows = build_cast_review(observations)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row['end_kind'] for row in rows], ['damage', 'cancel', None])
        self.assertEqual(rows[0]['elapsed_ms'], 500)
        self.assertIsNone(rows[-1]['packet_index'])
        self.assertTrue(all(row['association_confirmed'] is False for row in rows))
        wrong_scope = dict(observations[2], capture_session=99)
        self.assertEqual(build_cast_review([*observations, wrong_scope]), rows)
        self.assertEqual(observations, original)

    def effect(self, actor=42, target=99, result=1, timestamp=1):
        return packet(0x11a, struct.pack('<HhIIB', 347, 100, target, actor, result), timestamp=timestamp)

    def test_effect_arrival_intervals_are_scoped_to_individual_target_and_result(self):
        self.apply(mob(42))
        self.apply(mob(43))
        for event in (self.effect(), self.effect(actor=43, timestamp=1.1),
                      self.effect(target=98, timestamp=1.2), self.effect(result=0, timestamp=2),
                      self.effect(timestamp=3)):
            self.apply(event)
        row = self.skills.summaries(aggregate=True)[0]
        series = row['intervals']['capture_effect_notification']
        self.assertEqual(series['count'], 1)
        self.assertEqual(series['min_ms'], 2000)
        self.assertEqual(series['samples'][0]['target_id'], 99)
        self.assertEqual(series['samples'][0]['result'], 1)
        self.assertEqual(row['intervals']['server_tick_damage']['count'], 0)
        self.assertIsNone(row['configured_cooldown_ms'])

    def test_effect_unknown_target_and_unreliable_timestamps_do_not_form_intervals(self):
        self.apply(mob())
        self.apply(self.effect(target=0))
        self.apply(self.effect(target=0, timestamp=2))
        self.assertEqual(self.skills.summaries()[0]['intervals']['capture_effect_notification']['count'], 0)
        for timestamp in (5, 4, 6, 8):
            self.apply(self.effect(timestamp=timestamp))
        series = self.skills.summaries()[0]['intervals']['capture_effect_notification']
        self.assertEqual(series['count'], 1)
        self.assertEqual(series['min_ms'], 2000)

    def setUp(self):
        self.world = WorldStore()
        self.skills = SkillStore(self.world)
        self.ordinal = 0

    def apply(self, event, session=0):
        self.world.apply(event, session, self.ordinal)
        self.skills.apply(event, session, self.ordinal)
        self.ordinal += 1

    def test_individual_intervals_precede_class_aggregation(self):
        self.apply(mob(42))
        self.apply(mob(43))
        self.apply(damage(42, tick=1000))
        self.apply(damage(43, tick=1100, timestamp=1.1))
        self.apply(damage(42, tick=6000, timestamp=6))
        result = self.skills.summaries(aggregate=True)[0]
        self.assertEqual(result['source_appearances'], 2)
        interval = result['intervals']['server_tick_damage']
        self.assertEqual(interval['min_ms'], 5000)
        self.assertEqual(interval['count'], 1)
        self.assertEqual(interval['samples'][0]['from_packet_index'], 2)
        self.assertEqual(interval['samples'][0]['packet_index'], 4)
        self.assertIsNone(result['configured_cooldown_ms'])

    def test_multiple_targets_same_tick_and_unknown_level_not_substituted(self):
        self.apply(mob())
        self.apply(damage(target=98))
        self.apply(damage(target=99, timestamp=1.01))
        self.apply(damage(tick=6000, timestamp=6))
        result = self.skills.summaries()[0]
        self.assertEqual(result['counts']['damage'], 3)
        self.assertEqual(result['tick_groups'], 2)
        self.assertEqual(result['known_levels'], [])
        self.assertEqual(result['raw_levels'], [65535])
        self.assertEqual(result['unknown_level_notifications'], 3)
        self.assertEqual(result['intervals']['server_tick_damage']['count'], 1)

    def test_tick_wrap_and_signed_damage_are_preserved(self):
        self.apply(mob())
        self.apply(damage(tick=0xfffffff0, value=-1))
        self.apply(damage(tick=0x20, timestamp=1.05, level=3))
        self.assertEqual(self.skills.events[0]['damage'], -1)
        self.assertEqual(self.skills.events[1]['interval_ms'], 48)
        self.assertEqual(self.skills.summaries()[0]['known_levels'], [3])

    def test_death_reappearance_map_and_capture_boundaries(self):
        self.apply(mob())
        self.apply(damage())
        self.apply(packet(0x80, struct.pack('<IB', 42, 1), timestamp=2))
        self.apply(mob(timestamp=3))
        self.apply(damage(tick=5000, timestamp=5))
        self.assertEqual(len(self.skills.summaries()), 2)
        self.apply(map_packet(timestamp=6))
        self.apply(mob(timestamp=7))
        self.apply(damage(tick=8000, timestamp=8))
        self.apply(mob(timestamp=9), session=1)
        self.apply(damage(tick=10000, timestamp=10), session=1)
        self.assertEqual(len(self.skills.summaries()), 4)
        self.assertTrue(all(row['intervals']['server_tick_damage']['count'] == 0 for row in self.skills.summaries()))

    def test_class_change_and_connection_are_separate(self):
        self.apply(mob())
        self.apply(damage())
        self.apply(packet(0x1b0, struct.pack('<IBI', 42, 0, 1006), timestamp=2))
        self.apply(damage(tick=3000, timestamp=3))
        self.apply(mob(connection='other', timestamp=4))
        self.apply(damage(connection='other', tick=5000, timestamp=5))
        self.assertEqual(len(self.skills.summaries()), 3)
        self.assertEqual({row['class_id'] for row in self.skills.summaries()}, {1005, 1006})

    def test_cast_effect_and_cancel_links_are_per_individual(self):
        self.apply(mob())
        self.apply(mob(43))
        self.apply(cast())
        self.apply(damage(timestamp=1))
        self.assertEqual(self.skills.events[1]['linked_cast_index'], 2)
        self.assertEqual(self.skills.events[1]['cast_elapsed_ms'], 500)
        self.apply(cast(actor=43, timestamp=2, pid=0x7fb))
        self.apply(packet(0x1b9, struct.pack('<I', 43), timestamp=2.2))
        self.assertEqual(self.skills.events[-2]['cast_outcome'], 'cancelled')
        self.assertEqual(self.skills.events[-1]['skill_id'], 177)
        self.apply(packet(0x1b9, struct.pack('<I', 42), timestamp=2.3))
        self.assertEqual(len(self.skills.unmatched_cancels), 1)

    def test_wrong_target_expired_cast_and_interruption_do_not_claim_completion(self):
        self.apply(mob())
        self.apply(cast())
        self.apply(damage(target=100))
        self.assertNotIn('linked_cast_index', self.skills.events[-1])
        self.apply(damage(timestamp=30, tick=30000))
        self.assertNotIn('linked_cast_index', self.skills.events[-1])
        self.apply(packet(0x80, struct.pack('<IB', 42, 0), timestamp=31))
        self.assertEqual(self.skills.events[0]['cast_outcome'], 'interrupted')
        self.assertFalse(self.skills.pending)

    def test_non_damage_effect_value_is_not_a_level(self):
        self.apply(mob())
        self.apply(packet(0x11a, struct.pack('<HhIIB', 347, -1, 99, 42, 1)))
        self.apply(packet(0x9cb, struct.pack('<HiIIB', 347, 9999, 99, 42, 1)))
        result = self.skills.summaries()[0]
        self.assertEqual(result['known_levels'], [])
        self.assertEqual(self.skills.events[-1]['effect_value'], 9999)
        self.assertIsNone(self.skills.events[-1]['interval_ms'])

    def test_ground_skill_and_cast_intervals_use_separate_bases(self):
        self.apply(mob())
        self.apply(cast(timestamp=.1, target=0))
        self.apply(packet(0x117, struct.pack('<HIHHHI', 177, 42, 2, 10, 20, 1000), timestamp=1))
        self.apply(cast(timestamp=4, target=0))
        self.apply(packet(0x117, struct.pack('<HIHHHI', 177, 42, 2, 10, 20, 5000), timestamp=5))
        row = self.skills.summaries()[0]
        self.assertEqual(row['intervals']['server_tick_ground']['min_ms'], 4000)
        self.assertEqual(row['intervals']['capture_cast_start']['min_ms'], 3900)
        self.assertEqual(row['intervals']['server_tick_damage']['count'], 0)

    def test_reverse_timestamp_and_tick_exclude_intervals_then_recover(self):
        self.apply(mob())
        self.apply(damage(tick=1000, timestamp=1))
        self.apply(damage(tick=2000, timestamp=.5))
        self.apply(damage(tick=3000, timestamp=3))
        self.apply(damage(tick=4000, timestamp=4))
        self.assertIsNone(self.skills.events[1]['interval_ms'])
        self.assertIsNone(self.skills.events[2]['interval_ms'])
        self.assertEqual(self.skills.events[3]['interval_ms'], 1000)
        self.apply(damage(tick=3500, timestamp=5))
        self.assertIn('tick_reversed_or_ambiguous', self.skills.events[-1]['flags'])

    def test_unknown_source_and_npc_are_not_retroactively_assigned(self):
        self.apply(damage())
        self.apply(actor_packet(actor_type=6))
        self.apply(damage())
        self.apply(mob())
        self.assertEqual(self.skills.events, [])
        self.assertEqual(self.skills.unattributed, 2)
        self.apply(replace(damage(), direction='SEND'))
        self.assertEqual(self.skills.events, [])

    def test_malformed_packet_and_capacity_fail_closed(self):
        self.apply(mob())
        self.apply(packet(0x1de))
        self.assertEqual(self.skills.issue_count, 1)

        self.skills = SkillStore(self.world, max_entries=1)
        self.skills.apply(damage())
        self.skills.apply(damage(skill=190))
        self.assertEqual(len(self.skills.events), 1)
        self.assertTrue(self.skills.saturated)
        self.skills = SkillStore(self.world, max_events=1)
        self.skills.apply(damage())
        self.skills.apply(damage(tick=2000, timestamp=2))
        self.skills.apply(damage(tick=3000, timestamp=3))
        self.assertEqual(len(self.skills.events), 1)
        self.assertTrue(self.skills.saturated)
        self.assertEqual(self.skills.issue_count, 1)

    def test_external_names_are_validated_without_changing_stats(self):
        self.assertIn(177, load_skill_names())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'names.json'
            path.write_text(json.dumps(dict(version=1, skills={'177': 'test'})), encoding='utf-8')
            self.assertEqual(load_skill_names(path)[177], 'test')
            path.write_text(json.dumps(dict(version=1, skills={'0177': 'ambiguous'})), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_skill_names(path)

    def test_raw_log_replay_preserves_actor_and_packet_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            definitions = {0x9ff: -1, 0x1de: 33}
            log = SessionLog(folder, definitions, record_payload=True)
            log.write('capture_format', transport='tcp_segments')
            endpoints = ('server', 1, 'client', 2)
            log.write('tcp_segment', endpoints=endpoints, sequence=10, flags=2, data=b'', timestamp=0)
            payload = mob().raw + damage().raw
            log.write('tcp_segment', endpoints=endpoints, sequence=11, flags=16, data=payload, timestamp=1)
            log.close()
            report = analyze(log.path, definitions)
            self.assertEqual(len(report['observations']), 1)
            self.assertEqual(report['observations'][0]['packet_index'], 1)
            self.assertEqual(report['class_skills'][0]['class_id'], 1005)


if __name__ == '__main__':
    unittest.main()

