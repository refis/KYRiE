from tests.support.world import packet, actor_packet, name_packet, map_packet
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from events import PacketEvent
from capture.receiver import Receiver
from reconstruction.decoder import decode_world_event
from reconstruction.world import WorldStore
from storage.session_log import SessionLog
from tools.analyze_entities import main as analyze_main










class WorldTests(unittest.TestCase):
    def test_entities_use_character_bound_current_player_map_without_cross_flow_leaks(self):
        from tests.support.player import packet as player_packet
        world = WorldStore()
        hint = player_packet(0x71, struct.pack('<I', 123) + b'initial.gat'.ljust(16, b'\0') + bytes(6), flow='char')
        login = player_packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND', flow='game')
        world.apply(hint, packet_index=0)
        world.apply(login, packet_index=1)
        npc_packet = replace(actor_packet(actor_id=70, connection='receive-half'), flow_id='game')
        mob_packet = replace(actor_packet(actor_id=71, actor_type=5, connection='receive-half'), flow_id='game')
        world.apply(npc_packet, packet_index=2)
        world.apply(mob_packet, packet_index=3)
        for entity in world.records():
            self.assertEqual(entity.map_name, 'initial.gat')
            self.assertEqual(entity.map_origin, 'player_current_map')
            self.assertEqual(entity.map_evidence['observation']['packet_index'], 1)
            self.assertEqual(entity.map_evidence['map_hint']['packet_index'], 0)
        world.apply(actor_packet(actor_id=72, connection='other-flow'))
        self.assertIsNone(next(entity for entity in world.records() if entity.actor_id == 72).map_name)
        world.apply(replace(map_packet(name='next.gat', connection='receive-half'), flow_id='game'))
        world.apply(replace(npc_packet, timestamp=2))
        current = world.find_current(npc_packet, 0, 70)
        self.assertEqual(current.map_name, 'next.gat')
        self.assertEqual(current.map_generation, 1)
        previous = next(e for e in world.records() if e.actor_id == 70 and e.map_generation == 0)
        self.assertEqual(previous.map_name, 'initial.gat')
        self.assertEqual(previous.state, 'previous_map')
        world.apply(replace(npc_packet, connection='reconnected', flow_id='new-game'))
        self.assertIsNone(world.find_current(replace(npc_packet, connection='reconnected'), 0, 70).map_name)
        world.apply(npc_packet, session=1)
        self.assertIsNone(world.find_current(npc_packet, 1, 70).map_name)
        for bad_character in (999,):
            isolated = WorldStore()
            isolated.apply(hint)
            isolated.apply(player_packet(0x436, struct.pack('<II', 42, bad_character) + bytes(13),
                                        direction='SEND', flow='game'))
            isolated.apply(npc_packet)
            self.assertIsNone(isolated.records()[0].map_name)
        isolated = WorldStore()
        isolated.apply(player_packet(0x65, struct.pack('<I', 42) + bytes(11), direction='SEND', flow='char'))
        isolated.apply(hint)
        isolated.apply(player_packet(0x436, struct.pack('<II', 99, 123) + bytes(13), direction='SEND', flow='game'))
        isolated.apply(npc_packet)
        self.assertIsNone(isolated.records()[0].map_name)
        isolated = WorldStore()
        isolated.apply(replace(hint, raw=b'\x71\x00'))
        isolated.apply(login)
        isolated.apply(npc_packet)
        self.assertIsNone(isolated.records()[0].map_name)
        self.assertEqual(isolated.issue_count, 1)

    def test_spawn_idle_and_move_name_offsets(self):
        for pid in (0x9fe, 0x9ff, 0x9fd):
            with self.subTest(pid=pid):
                observation = decode_world_event(actor_packet(pid=pid, name='確認NPC'))
                self.assertEqual(observation.fields['name'], '確認NPC')
                self.assertEqual((observation.fields['x'], observation.fields['y']), (150, 200))
                self.assertEqual(observation.actor_id, 42)

    def test_actor_fields_and_packed_movement(self):
        world = WorldStore()
        world.apply(map_packet())
        world.apply(actor_packet(), packet_index=17)
        npc = world.records('NPC')[0]
        self.assertEqual((npc.name, npc.actor_id, npc.class_id, npc.map_name), ('案内人', 42, 45, 'prontera.gat'))
        self.assertEqual((npc.x, npc.y, npc.direction, npc.speed), (150, 200, 3, 150))
        self.assertEqual(npc.options, 0x12345678)
        self.assertEqual(npc.evidence[-1]['packet_index'], 17)
        world.apply(actor_packet(pid=0x9fd, actor_type=12, x=160, y=210, name='', timestamp=2))
        self.assertEqual(len(world.records('NPC')), 1)
        self.assertEqual((npc.x, npc.y, npc.destination_x, npc.destination_y), (160, 210, 300, 400))
        self.assertEqual(npc.name, '案内人')
        world.apply(actor_packet(name='', timestamp=3))
        self.assertIsNone(npc.destination_x)

    def test_npc_mob_and_other_types_are_not_conflated(self):
        world = WorldStore()
        for aid, kind in ((1, 5), (2, 6), (3, 12), (4, 0), (5, 7)):
            world.apply(actor_packet(actor_id=aid, actor_type=kind))
        self.assertEqual(len(world.records('MOB')), 1)
        self.assertEqual(len(world.records('NPC')), 2)
        world.apply(actor_packet(actor_id=2, actor_type=0))
        self.assertEqual(world.records('NPC')[0].state, 'replaced')

    def test_connection_map_and_capture_scopes_do_not_leak(self):
        world = WorldStore()
        world.apply(actor_packet())
        world.apply(actor_packet(connection='flow-b', name='別のNPC'))
        self.assertEqual(len(world.records('NPC')), 2)
        self.assertIsNone(world.records('NPC')[0].map_name)
        world.apply(map_packet())
        world.apply(actor_packet(name='移動先NPC'))
        self.assertEqual(len(world.records('NPC')), 3)
        old = next(x for x in world.records() if x.connection == 'flow-a' and x.map_generation == 0)
        self.assertEqual(old.state, 'previous_map')
        current = next(x for x in world.records() if x.map_generation == 1)
        self.assertEqual(current.map_name, 'prontera.gat')
        world.apply(actor_packet(name='次回の観測'), session=1)
        self.assertEqual(len(world.records('NPC')), 4)
        self.assertEqual(len(world.records(active_only=True)), 1)
        self.assertTrue(all(x.state == 'past_capture' for x in world.records() if x.capture_session == 0 and x.state != 'previous_map'))

    def test_remove_and_reappearance_keep_separate_records(self):
        world = WorldStore()
        world.apply(actor_packet(actor_type=5))
        world.apply(packet(0x80, struct.pack('<IB', 42, 1)))
        world.apply(actor_packet(actor_type=5, timestamp=3))
        mobs = world.records('MOB')
        self.assertEqual(len(mobs), 2)
        self.assertEqual([(x.appearance, x.state) for x in mobs], [(1, 'dead'), (2, 'visible')])
        self.assertEqual(mobs[0].removal_reason, 1)
        self.assertEqual(len(world.records('MOB', active_only=True)), 1)

    def test_name_before_and_after_actor_is_scoped_and_does_not_create_ghosts(self):
        world = WorldStore()
        world.apply(name_packet())
        self.assertFalse(world.records())
        world.apply(actor_packet(name=''))
        npc = world.records()[0]
        self.assertEqual((npc.name, npc.title, npc.group_id), ('正式名', '案内', 7))
        world.apply(name_packet(name='改名', title='更新', timestamp=3))
        self.assertEqual(npc.name, '改名')
        self.assertEqual(npc.evidence[-1]['packet_id'], 0xadf)
        world.apply(name_packet(connection='flow-b', name='他接続'))
        self.assertEqual(npc.name, '改名')

    def test_fixed_name_without_nul_keeps_last_character(self):
        world = WorldStore()
        world.apply(actor_packet(name=''))
        world.apply(packet(0x95, struct.pack('<I', 42) + b'abcdefghijklmnopqrstuvwx'))
        self.assertEqual(world.records()[0].name, 'abcdefghijklmnopqrstuvwx')

    def test_malformed_encoding_keeps_verified_numeric_fields_and_later_recovers(self):
        world = WorldStore()
        world.apply(actor_packet(raw_name=b'\x81'))
        npc = world.records()[0]
        self.assertEqual((npc.actor_id, npc.x, npc.y, npc.name), (42, 150, 200, ''))
        self.assertIn('name', npc.field_issues)
        self.assertEqual(world.issue_count, 1)
        world.apply(name_packet())
        self.assertEqual(npc.name, '正式名')
        self.assertNotIn('name', npc.field_issues)
        self.assertIn('field_issues', npc.evidence[0])

    def test_short_or_inconsistent_actor_packet_does_not_mutate_existing_state(self):
        world = WorldStore()
        world.apply(actor_packet())
        before = world.snapshot()['entities']
        world.apply(packet(0x9ff, b'\x05\x00x'))
        raw = bytearray(actor_packet().raw)
        struct.pack_into('<H', raw, 2, len(raw) + 1)
        world.apply(PacketEvent(2, 'RECV', 0x9ff, bytes(raw), 'NPCAP', 'flow-a'))
        self.assertEqual(world.snapshot()['entities'], before)
        self.assertEqual(world.issue_count, 2)

    def test_updates_preserve_health_and_full_option_flags(self):
        world = WorldStore()
        world.apply(actor_packet(actor_type=5))
        world.apply(packet(0x977, struct.pack('<III', 42, 123, 500)))
        world.apply(packet(0xa36, struct.pack('<IB', 42, 19)))
        world.apply(packet(0x88, struct.pack('<IHH', 42, 101, 202)))
        world.apply(packet(0x1b0, struct.pack('<IBI', 42, 0, 2001)))
        world.apply(packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 0xf1234567, 0)))
        mob = world.records('MOB')[0]
        self.assertEqual((mob.hp, mob.max_hp, mob.hp_percent), (123, 500, 95))
        self.assertEqual((mob.x, mob.y, mob.class_id, mob.options), (101, 202, 2001, 0xf1234567))

    def test_unknown_updates_and_send_packets_do_not_invent_entities(self):
        world = WorldStore()
        world.apply(packet(0x88, struct.pack('<IHH', 42, 10, 20)))
        source = actor_packet()
        world.apply(PacketEvent(1, 'SEND', source.packet_id, source.raw, 'NPCAP', source.connection))
        world.apply(packet(0xffff))
        self.assertFalse(world.records())
        self.assertEqual(world.issue_count, 0)
        world.apply(name_packet())
        world.apply(actor_packet(actor_type=0))
        world.apply(actor_packet(name=''))
        self.assertEqual(world.records()[0].name, '')

    def test_capacity_and_evidence_history_are_bounded(self):
        world = WorldStore(max_entities=1, max_pending_names=1)
        world.apply(actor_packet())
        world.apply(actor_packet(actor_id=43))
        self.assertEqual(len(world.records()), 1)
        self.assertEqual(world.issue_count, 1)
        for index in range(40):
            world.apply(packet(0x88, struct.pack('<IHH', 42, index, index)))
        self.assertEqual(len(world.records()[0].evidence), 32)
        world.apply(name_packet(actor_id=51))
        world.apply(name_packet(actor_id=52))
        self.assertEqual(len(world.pending_names), 1)
        self.assertEqual(world.evicted_names, 1)

    def test_late_previous_capture_event_updates_archive_without_leaking(self):
        world = WorldStore()
        world.apply(actor_packet(), session=0)
        world.begin_capture(1)
        world.apply(actor_packet(name='遅れて到着', timestamp=2), session=0)
        self.assertEqual(len(world.records()), 1)
        self.assertFalse(world.records()[0].active)
        self.assertEqual(world.records()[0].name, '遅れて到着')
        world.apply(actor_packet(name='現セッション'), session=1)
        self.assertEqual(len(world.records()), 2)
        self.assertEqual(world.records(active_only=True)[0].name, '現セッション')

    def test_entity_cli_replays_and_writes_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            definitions = {0x9ff: -1}
            log = SessionLog(folder, definitions, record_payload=True)
            receiver = Receiver('', None, definitions, lambda event: None, lambda message: None, recorder=log)
            key = ('server', 5121, 'client', 50000)
            receiver._consume(key, 100, 0x12, b'', 1)
            receiver._consume(key, 101, 0x10, actor_packet().raw + actor_packet(actor_id=43, actor_type=5).raw, 2)
            log.close()
            output = Path(folder) / 'entities.json'
            with patch('sys.argv', ['analyze_entities', str(log.path), '--definitions',
                       str(log.directory / 'PacketLength.used.txt'), '--output', str(output)]), \
                 patch('sys.stdout', new=io.StringIO()):
                analyze_main()
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['entity_counts'], {'NPC': 1, 'MOB': 1})
            self.assertEqual(result['issue_count'], 0)
            self.assertEqual(result['entities'][0]['evidence'][0]['packet_id'], 0x9ff)
            self.assertTrue(result['definitions_sha256'])


    def test_real_spawn_name_trailing_cp932_lead_is_diagnostic_not_authoritative(self):
        data=bytes.fromhex('23835283938370835870726f5f61735f837a838d839390')
        raw=bytearray(actor_packet(raw_name=data).raw[:-1])
        struct.pack_into('<H',raw,2,len(raw))
        event=replace(actor_packet(),raw=bytes(raw))
        world=WorldStore();world.apply(event,packet_index=7)
        npc=world.records()[0]
        self.assertEqual(npc.name,'')
        self.assertEqual((npc.x,npc.y),(150,200))
        diagnostic=npc.metadata_evidence['name_diagnostic']
        self.assertEqual(diagnostic['raw_hex'],data.hex())
        self.assertEqual(diagnostic['valid_prefix'],data[:-1].decode('cp932'))
        self.assertFalse(diagnostic['authoritative_name'])
        self.assertEqual(diagnostic['observed_bytes'],23)
        self.assertEqual(diagnostic['evidence']['packet_index'],7)
        self.assertEqual(world.issue_count,1)
        self.assertIn('name_diagnostic',npc.evidence[0])
        world.apply(name_packet(name='正式な名前'),packet_index=8)
        self.assertEqual(npc.name,'正式な名前')
        self.assertNotIn('name_diagnostic',npc.metadata_evidence)
        self.assertNotIn('name',npc.field_issues)
        world.apply(event,packet_index=9)
        self.assertEqual(npc.name,'正式な名前')
        self.assertIn('name_diagnostic',npc.metadata_evidence)
        malformed=bytearray(raw);malformed[84:87]=b'\x81\x20X'
        decoded=decode_world_event(replace(event,raw=bytes(malformed)))
        self.assertNotIn('name_diagnostic',decoded.fields)
        self.assertIn('name',decoded.field_issues)
        world.apply(replace(event,raw=bytes(malformed)),packet_index=10)
        self.assertNotIn('name_diagnostic',npc.metadata_evidence)
        self.assertEqual(npc.name,'正式な名前')
