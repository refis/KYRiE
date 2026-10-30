import struct
import unittest
from dataclasses import replace

from reconstruction.actor_identity import server_endpoint
from reconstruction.world import WorldStore
from tests.support.world import actor_packet, map_packet, packet


def connection(ip='18.1.2.3', port=5121, client_port=50000):
    return str((ip, port, '192.168.1.2', client_port)) + ' [SYN=123]'


class ActorIdentityTests(unittest.TestCase):
    def test_server_namespace_ignores_client_port_but_separates_server_port_and_capture(self):
        world = WorldStore()
        for capture, endpoint in ((0, connection()), (0, connection(client_port=50001)),
                                  (0, connection(port=5122)), (0, connection(ip='18.1.2.4')), (1, connection())):
            world.apply(actor_packet(actor_id=1001, connection=endpoint), session=capture)
        groups = world.snapshot()['server_actor_observations']['groups']
        self.assertEqual(len(groups), 4)
        self.assertEqual(sorted(group['visibility_intervals'] for group in groups), [1, 1, 1, 2])
        self.assertTrue(all(not group['same_entity_confirmed'] for group in groups))
        sent = replace(packet(0x7e), direction='SEND',
                       connection=str(('192.168.1.2', 50000, '18.1.2.3', 5121)) + ' [SYN=99]')
        self.assertEqual(server_endpoint(sent), {'ip': '18.1.2.3', 'port': 5121})
        for label in ('flow-a', "('bad', 5121, 'client', 1)", "('18.1.2.3', True, 'client', 1)"):
            self.assertIsNone(server_endpoint(replace(sent, direction='RECV', connection=label)))

    def test_visibility_exit_keeps_actor_id_in_one_namespace_with_distinct_observation_intervals(self):
        world = WorldStore()
        endpoint = connection()
        world.apply(map_packet(connection=endpoint))
        world.apply(actor_packet(actor_id=1001, connection=endpoint))
        world.apply(packet(0x80, struct.pack('<IB', 1001, 0), connection=endpoint))
        world.apply(actor_packet(actor_id=1001, connection=endpoint))
        rows = world.snapshot()['entities']
        self.assertEqual([row['actor_id'] for row in rows], [1001, 1001])
        self.assertEqual([row['appearance'] for row in rows], [1, 2])
        group = world.snapshot()['server_actor_observations']['groups'][0]
        self.assertEqual(group['visibility_intervals'], 2)
        self.assertEqual(group['allocation_kind'], 'not_determined')

    def test_consecutive_ids_are_preserved_without_inventing_spawn_counts_or_static_allocation(self):
        world = WorldStore()
        endpoint = connection()
        for actor in range(1001, 1201):
            world.apply(actor_packet(actor_id=actor, actor_type=5, connection=endpoint))
        report = world.snapshot('MOB')['server_actor_observations']
        self.assertEqual([group['actor_id'] for group in report['groups']], list(range(1001, 1201)))
        self.assertFalse(report['script_spawn_count_inferred'])
        world.apply(map_packet('1@toy.gat', connection=endpoint))
        world.apply(actor_packet(actor_id=912345, actor_type=5, connection=endpoint))
        instance = next(group for group in world.snapshot()['server_actor_observations']['groups'] if group['actor_id'] == 912345)
        self.assertEqual(instance['allocation_kind'], 'instance_runtime')
        self.assertFalse(instance['same_entity_confirmed'])

    def test_actor_order_groups_numeric_server_and_port_before_numeric_actor(self):
        for kind in (5,6):
            with self.subTest(kind=kind):
                world=WorldStore()
                records=[('10.0.0.10',5121,1),('10.0.0.2',6121,1),('10.0.0.2',5121,10),('10.0.0.2',5121,2)]
                for ip,port,aid in records:
                    world.apply(actor_packet(actor_id=aid,actor_type=kind,connection=connection(ip,port)))
                world.apply(actor_packet(actor_id=3,actor_type=kind,connection='unknown'))
                ordered=world.records('MOB' if kind==5 else 'NPC')
                self.assertEqual([row.actor_id for row in ordered],[2,10,1,1,3])
                self.assertEqual([row.server_endpoint for row in ordered[:-1]],
                    [dict(ip=ip,port=port) for ip,port in [('10.0.0.2',5121),('10.0.0.2',5121),('10.0.0.2',6121),('10.0.0.10',5121)]])
