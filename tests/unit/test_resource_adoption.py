from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.player import PlayerStore
from tests.support.dialogue import packet
from tests.support.player import pickup


class ResourceAdoptionTests(unittest.TestCase):
    def consume(self, store, players, event):
        index = store.packet_ordinal
        values = players.apply(event, packet_index=index)
        store.apply(event, packet_index=index, player_observation=values)

    def conversation_with_resources(self):
        store, players = DialogueStore(), PlayerStore()
        events = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0x142, struct.pack('<I', 42)),
                  packet(0xb1, struct.pack('<HI', 20, 1000)),
                  packet(0xb1, struct.pack('<HI', 20, 800)),
                  replace(pickup(), flow_id='flow', connection='half', timestamp=1),
                  packet(0xaf, struct.pack('<HH', 2, 1)),
                  packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'continued\0'),
                  packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20))]
        for event in events:
            self.consume(store, players, event)
        return store, store.sessions[0]

    def test_unconfirmed_resources_stay_comments_without_zeny_or_warp_commands(self):
        store, item = self.conversation_with_resources()
        self.assertTrue(all(row.get('adoption_confirmed') is False for row in item.resource_observations))
        self.assertTrue(all(row['cause_confirmed'] is False for row in item.resource_observations))
        code = AurigaRenderer().render(item)
        self.assertIn('観測差分 -200', code)
        self.assertNotIn('set Zeny,Zeny', code)
        self.assertNotIn('warp "test.gat"', code)
        self.assertIn('getitem 501,3;', code)
        before = deepcopy(item.resource_observations)
        AurigaRenderer().render(item)
        self.assertEqual(item.resource_observations, before)

    def test_confirmed_zeny_and_map_emit_commands_while_cause_stays_false(self):
        store, item = self.conversation_with_resources()
        zeny = next(row for row in item.resource_observations
                    if row['kind'] == 'zeny' and row['fields']['delta_known'])
        destination = next(row for row in item.resource_observations if row['kind'] == 'map')
        store.set_resource_adoption(item, zeny['packet_index'], True)
        store.set_resource_adoption(item, destination['packet_index'], True)
        self.assertTrue(zeny['adoption_confirmed'])
        self.assertFalse(zeny['cause_confirmed'])
        code = AurigaRenderer().render(item)
        self.assertIn('set Zeny,Zeny-200;', code)
        self.assertIn('warp "test.gat",10,20;', code)
        self.assertIn('確認済み観測', code)
        store.set_resource_adoption(item, zeny['packet_index'], False)
        code = AurigaRenderer().render(item)
        self.assertNotIn('set Zeny,Zeny', code)
        self.assertIn('warp "test.gat",10,20;', code)

    def test_unknown_zeny_and_instance_map_stay_non_executable(self):
        store, item = self.conversation_with_resources()
        unknown = next(row for row in item.resource_observations
                       if row['kind'] == 'zeny' and not row['fields']['delta_known'])
        store.set_resource_adoption(item, unknown['packet_index'], True)
        code = AurigaRenderer().render(item)
        self.assertNotIn('set Zeny,Zeny', code)
        destination = next(row for row in item.resource_observations if row['kind'] == 'map')
        destination['fields']['map_name'] = '1@test.gat'
        store.set_resource_adoption(item, destination['packet_index'], True)
        code = AurigaRenderer().render(item)
        self.assertTrue(any(line.strip().startswith('//') and '1@test.gat' in line for line in code.splitlines()))
        self.assertFalse(any(line.strip().startswith('warp ') for line in code.splitlines()))

    def test_confirmed_item_without_duplicate_when_script_command_exists(self):
        store, item = self.conversation_with_resources()
        gain = next(row for row in item.resource_observations if row['kind'] == 'item_gain')
        before = AurigaRenderer().render(item).count('getitem 501,3;')
        store.set_resource_adoption(item, gain['packet_index'], True)
        after = AurigaRenderer().render(item).count('getitem 501,3;')
        self.assertEqual(before, 1)
        self.assertEqual(after, 1)

    def test_confirmed_base_and_job_exp_gains_emit_getexp(self):
        store, players = DialogueStore(), PlayerStore()
        events = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0x142, struct.pack('<I', 42)),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                  packet(0xb0, struct.pack('<HI', 1, 1000)),
                  packet(0xb0, struct.pack('<HI', 1, 1500)),
                  packet(0xb0, struct.pack('<HI', 2, 20)),
                  packet(0xb0, struct.pack('<HI', 2, 35)),
                  packet(0xb6, struct.pack('<I', 42)),
                  packet(0x146, struct.pack('<I', 42), 'SEND')]
        for event in events:
            self.consume(store, players, event)
        item = store.sessions[0]
        base = next(row for row in item.resource_observations
                    if row['kind'] == 'base_exp' and row['fields'].get('delta_positive'))
        job = next(row for row in item.resource_observations
                   if row['kind'] == 'job_exp' and row['fields'].get('delta_positive'))
        store.set_resource_adoption(item, base['packet_index'], True)
        store.set_resource_adoption(item, job['packet_index'], True)
        code = AurigaRenderer().render(item)
        self.assertIn('getexp 500,0,0;', code)
        self.assertIn('getexp 0,15,0;', code)
        unknown = next(row for row in item.resource_observations
                       if row['kind'] == 'base_exp' and not row['fields']['delta_known'])
        store.set_resource_adoption(item, unknown['packet_index'], True)
        code = AurigaRenderer().render(item)
        self.assertEqual(code.count('getexp 500,0,0;'), 1)

    def test_adoption_api_rejects_quests_and_missing_rows(self):
        store, item = self.conversation_with_resources()
        item.resource_observations.append(dict(kind='quest_add', fields={'quest_id': 1, 'state': 0},
            cause_confirmed=False, adoption_confirmed=False, after_step_index=0, packet_index=99,
            packet_id=0x2b3, timestamp=1.0, connection='half', source='TEST', direction='RECV',
            capture_session=0, flow_id='flow'))
        with self.assertRaisesRegex(ValueError, 'Quest'):
            store.set_resource_adoption(item, 99, True)
        with self.assertRaisesRegex(ValueError, 'not found'):
            store.set_resource_adoption(item, 123456, True)
