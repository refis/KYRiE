from tests.support.combat import attack
from dataclasses import replace
import struct
import tempfile
import unittest

from parser.display import ReceiveDisplay, DisplayProfile
from reconstruction.combat import CombatStore, decode_attack
from reconstruction.decoder import ObservationError
from reconstruction.world import WorldStore
from storage.session_log import SessionLog
from tools.analyze_combat import analyze
from tests.support.skills import mob
from tests.support.world import packet, map_packet




class CombatTests(unittest.TestCase):
    def setUp(self):
        self.world = WorldStore()
        self.combat = CombatStore(self.world)
        self.index = 0

    def apply(self, event, session=0):
        self.world.apply(event, session, self.index)
        self.combat.apply(event, session, self.index)
        self.index += 1

    def test_all_layouts_keep_signed_values_and_bounds(self):
        for pid in (0x8a, 0x2e1, 0x8c8):
            result = decode_attack(attack(pid=pid, damage=-1, left=-2, divisions=3, sp=1))
            self.assertEqual(result['damage'], -1)
            self.assertEqual(result['left_damage'], -2)
            self.assertEqual(result['divisions'], 3)
            self.assertEqual(result['source_delay'], 120)
            self.assertEqual(result['sp_damage'], int(pid == 0x8c8))
            with self.assertRaises(ObservationError):
                decode_attack(packet(pid))

    def test_outgoing_incoming_roles_and_two_hands_are_not_multiplied(self):
        self.apply(mob())
        self.apply(mob(43, class_id=1006))
        self.apply(attack(target=43, damage=10, left=20, divisions=5))
        rows = self.combat.summaries(aggregate=True)
        self.assertEqual(rows[0]['damage']['outgoing']['hp_damage_total']['min'], 30)
        self.assertEqual(rows[1]['damage']['incoming']['hp_damage_total']['max'], 30)
        self.assertEqual(rows[0]['counts']['outgoing'], 1)
        self.assertEqual(rows[1]['counts']['incoming'], 1)
        self.assertEqual(rows[1]['damage']['incoming']['target_delay']['min'], 80)
        self.assertEqual(rows[0]['damage_contexts'][0]['counterparty_class_id'], 1006)
        self.assertIsNone(rows[0]['base_atk'])
        self.assertIsNone(rows[0]['base_def'])
        self.assertEqual(self.combat.snapshot()['attack_packet_count'], 1)

    def test_noncombat_actions_and_unknown_type_are_excluded(self):
        self.apply(mob())
        for action in (1, 2, 3, 255):
            self.apply(attack(action=action))
        self.assertEqual(self.combat.ignored_actions, 4)
        self.assertEqual(self.combat.summaries()[0]['counts'], {'state': 1})

    def test_special_negative_and_sp_damage_do_not_pollute_hp_range(self):
        self.apply(mob())
        self.apply(attack(damage=-1, left=50))
        self.apply(attack(damage=999, sp=1))
        self.apply(attack(damage=777, sp=2))
        self.apply(attack(damage=10, left=5))
        damage = self.combat.summaries()[0]['damage']['outgoing']
        self.assertEqual(damage['hp_damage_total']['count'], 1)
        self.assertEqual(damage['hp_damage_total']['min'], 15)
        self.assertEqual(damage['special_damage_notifications'], 1)
        self.assertEqual(damage['sp_notifications'], 1)
        self.assertEqual(damage['unknown_sp_flag_notifications'], 1)

    def test_individual_target_type_and_hp_sp_intervals_are_separate(self):
        self.apply(mob())
        self.apply(mob(43))
        self.apply(attack(actor=42, tick=1000))
        self.apply(attack(actor=43, tick=1100, timestamp=1.1))
        self.apply(attack(actor=42, tick=6000, timestamp=6))
        self.apply(attack(actor=42, target=100, tick=6100, timestamp=6.1))
        self.apply(attack(actor=42, action=10, tick=6200, timestamp=6.2))
        self.apply(attack(actor=42, sp=1, tick=6300, timestamp=6.3))
        self.apply(attack(actor=42, sp=1, tick=6400, timestamp=6.4))
        row = self.combat.summaries(aggregate=True)[0]
        self.assertEqual(row['outgoing_tick_interval']['min'], 5000)
        self.assertEqual(row['outgoing_tick_interval']['count'], 1)
        self.assertEqual(row['outgoing_sp_tick_interval']['min'], 100)
        sample = row['outgoing_tick_interval']['samples'][0]
        self.assertEqual((sample['from_packet_index'], sample['packet_index']), (2, 4))

    def test_tick_wrap_reverse_and_recovery(self):
        self.apply(mob())
        self.apply(attack(tick=0xfffffff0))
        self.apply(attack(tick=0x20, timestamp=2))
        self.assertEqual(self.combat.events[-1]['interval_ms'], 48)
        self.apply(attack(tick=0x30, timestamp=1.5))
        self.assertIsNone(self.combat.events[-1]['interval_ms'])
        self.apply(attack(tick=0x40, timestamp=3))
        self.assertIsNone(self.combat.events[-1]['interval_ms'])
        self.apply(attack(tick=0x50, timestamp=4))
        self.assertEqual(self.combat.events[-1]['interval_ms'], 16)

    def test_lifecycle_boundaries_and_counterparty_reappearance(self):
        self.apply(mob())
        self.apply(mob(43, class_id=1006))
        self.apply(attack(target=43))
        self.apply(packet(0x80, struct.pack('<IB', 43, 1), timestamp=2))
        self.apply(mob(43, class_id=1006, timestamp=3))
        self.apply(attack(target=43, tick=4000, timestamp=4))
        row = self.combat.summaries(entity_key=self.world.records('MOB')[0].key)[0]
        self.assertEqual(row['outgoing_tick_interval']['count'], 0)
        self.apply(map_packet(timestamp=5))
        self.apply(mob(timestamp=6))
        self.apply(attack(tick=7000, timestamp=7))
        self.apply(mob(timestamp=8), session=1)
        self.apply(attack(tick=9000, timestamp=9), session=1)
        self.assertTrue(all(r['outgoing_tick_interval']['count'] == 0 for r in self.combat.summaries()))

    def test_hp_speed_are_direct_samples_and_invalid_hp_is_flagged(self):
        self.apply(mob())
        self.apply(packet(0x977, struct.pack('<III', 42, 80, 100)))
        self.apply(packet(0xa36, struct.pack('<IB', 42, 10)))
        self.apply(packet(0x977, struct.pack('<III', 42, 500, 200)))
        row = self.combat.summaries()[0]
        self.assertEqual(row['speeds'], [150])
        self.assertEqual(row['observed_max_hp'], [100])
        self.assertEqual(row['hp_samples'][1]['hp_percent'], 50)
        self.assertIn('hp_exceeds_max', row['hp_samples'][-1]['flags'])
        self.apply(packet(0x977, struct.pack('<Iii', 42, -1, -1)))
        row = self.combat.summaries()[0]
        self.assertIn('invalid_hp_values', row['hp_samples'][-1]['flags'])
        self.assertEqual(row['observed_max_hp'], [100])

    def test_source_and_target_class_changes_do_not_share_interval_series(self):
        self.apply(mob())
        self.apply(mob(43, class_id=1006))
        self.apply(attack(target=43))
        self.apply(packet(0x1b0, struct.pack('<IBI', 43, 0, 1007), timestamp=2))
        self.apply(attack(target=43, tick=3000, timestamp=3))
        self.apply(packet(0x1b0, struct.pack('<IBI', 42, 0, 1008), timestamp=4))
        self.apply(attack(target=43, tick=5000, timestamp=5))
        self.assertTrue(all(row['outgoing_tick_interval']['count'] == 0 for row in self.combat.summaries()))

    def test_unknown_source_not_retroactively_assigned_and_other_flow_ignored(self):
        self.apply(attack())
        self.apply(mob())
        self.apply(attack(connection='other'))
        self.apply(replace(attack(), direction='SEND'))
        self.assertEqual(self.combat.unattributed, 2)
        self.assertEqual(self.combat.summaries()[0]['counts'], {'state': 1})

    def test_capacity_is_atomic_for_two_mob_roles(self):
        self.apply(mob())
        self.apply(mob(43))
        self.combat = CombatStore(self.world, max_events=1)
        self.combat.apply(attack(target=43))
        self.assertEqual(self.combat.events, [])
        self.assertTrue(self.combat.saturated)
        self.assertEqual(self.combat.issue_count, 1)

    def test_display_signed_fields_and_non_attack_action(self):
        display = ReceiveDisplay(DisplayProfile.load())
        result = display.decode(attack(damage=-1, left=-2))
        self.assertEqual(result.fields['damage'], -1)
        self.assertEqual(result.fields['left_damage'], -2)
        self.assertIn('left=-2', result.text)
        self.assertIn('攻撃集計対象外', display.decode(attack(action=1)).text)

    def test_offline_replay_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            definitions = {0x9ff: -1, 0x8c8: 34}
            log = SessionLog(folder, definitions, record_payload=True)
            log.write('capture_format', transport='tcp_segments')
            endpoints = ('server', 1, 'client', 2)
            log.write('tcp_segment', endpoints=endpoints, sequence=10, flags=2, data=b'', timestamp=0)
            log.write('tcp_segment', endpoints=endpoints, sequence=11, flags=16,
                      data=mob().raw + attack().raw, timestamp=1)
            log.close()
            report = analyze(log.path, definitions)
            self.assertEqual(report['class_performance'][0]['damage']['outgoing']['hp_damage_total']['min'], 10)
            self.assertEqual(report['observations'][-1]['packet_index'], 1)


if __name__ == '__main__':
    unittest.main()

