import json
import struct
import unittest
from copy import deepcopy
from dataclasses import replace

from reconstruction.dialogue import DialogueStore
from reconstruction.player import PlayerStore
from reconstruction.world import WorldStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.npc_bundle import build_npc_bundle
from reconstruction.script_commands import render_command
from tests.support.world import actor_packet, map_packet, packet as raw_packet
from tests.support.player import packet, pickup
from tests.support.dialogue import packet as dialogue_packet


class ScriptCommandTests(unittest.TestCase):
    def setup_store(self, opened=True, gear=False, split_connections=False):
        world, players = WorldStore(), PlayerStore()
        store = DialogueStore(world=world)
        def consume(event):
            connection=('recv-half' if event.direction=='RECV' else 'send-half') if split_connections else 'game'
            event = replace(event, connection=connection, flow_id='game', timestamp=1+store.packet_ordinal*.1)
            index=store.packet_ordinal
            world.apply(event,packet_index=index)
            values=players.apply(event,packet_index=index)
            store.apply(event,packet_index=index,player_observation=values)
        consume(map_packet('test.gat'))
        consume(raw_packet(0x283,struct.pack('<I',777)))
        consume(actor_packet(name='Guide'))
        if gear:
            consume(packet(0xb08,b'\0'))
            row=bytearray(67)
            struct.pack_into('<HI',row,0,2,1101)
            row[6]=4
            struct.pack_into('<I',row,11,2)
            row[15]=7
            consume(packet(0xb0a,b'\0'+row))
            consume(packet(0xb0b,b'\0\0'))
        if opened:
            consume(raw_packet(0x90,struct.pack('<IB',42,1),direction='SEND'))
            consume(dialogue_packet(0xb4,struct.pack('<I',42)+b'hello\0'))
        return world,store,consume

    def close(self,consume):
        consume(raw_packet(0xb6,struct.pack('<I',42)))

    def code(self,store):
        return AurigaRenderer().render(store.sessions[0])

    def test_openstorage_has_no_dialogue_gate_and_amount_updates_do_not_reopen(self):
        _,store,consume=self.setup_store(opened=False)
        for event in (raw_packet(0xf2,struct.pack('<HH',1,600)),raw_packet(0xf2,struct.pack('<HH',2,600)),
                      raw_packet(0xf8),raw_packet(0xf2,struct.pack('<HH',2,600))):
            consume(event)
        records=store.snapshot()['script_command_observations']
        self.assertEqual(len(records),2)
        self.assertTrue(all(render_command(r['fields'],AurigaRenderer().templates)=='openstorage;' for r in records))
        self.assertFalse(store.sessions)

    def test_getitem_getitem2_and_delitem_keep_attributes_and_gate_on_dialogue(self):
        _,store,consume=self.setup_store()
        consume(pickup(index=2,item_id=501,amount=3))
        decorated=bytearray(pickup(index=3,item_id=1101,amount=1).raw)
        decorated[68]=7
        struct.pack_into('<I',decorated,12,4001)
        consume(replace(pickup(),raw=bytes(decorated)))
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        self.close(consume)
        code=self.code(store)
        self.assertIn('getitem 501,3;',code)
        self.assertIn('getitem2 1101,1,1,7,0,4001,0,0,0;',code)
        self.assertIn('delitem 501,1;',code)
        _,outside,consume=self.setup_store(opened=False)
        consume(pickup())
        self.assertFalse(outside.commands.observations)

    def test_unrepresentable_grade_and_unknown_loss_id_are_review_only(self):
        _,store,consume=self.setup_store()
        event=pickup();raw=bytearray(event.raw);raw[69]=2
        consume(replace(event,raw=bytes(raw)))
        # An unknown inventory index is rejected by PlayerStore before command generation.
        consume(packet(0xaf,struct.pack('<HH',99,1)))
        self.close(consume)
        code=self.code(store)
        self.assertIn('// getitem2 ',code)
        self.assertFalse(any(line.startswith('getitem2 ') for line in code.splitlines()))
        self.assertTrue(store.issue_count)

    def test_equipped_loss_emits_delequip_and_refine_failure_suppresses_duplicate_loss(self):
        _,store,consume=self.setup_store(gear=True)
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        self.close(consume)
        self.assertIn('delequip 4;',self.code(store))
        _,store,consume=self.setup_store(gear=True)
        consume(packet(0x99a,struct.pack('<HIB',2,2,0)))
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        consume(packet(0x188,struct.pack('<HHH',1,2,0)))
        self.close(consume)
        code=self.code(store)
        active=[line for line in code.splitlines() if not line.startswith('//')]
        self.assertIn('failedrefitem 4;',active)
        self.assertFalse(any(line.startswith(('unequip ','delitem ','delequip ')) for line in active))

    def test_success_and_down_refine_use_observed_slot_and_decrement(self):
        for result,after,expected in ((0,8,'successrefitem 4;'),(2,5,'downrefitem 4,2;')):
            with self.subTest(result=result):
                _,store,consume=self.setup_store(gear=True)
                consume(packet(0x188,struct.pack('<HHH',result,2,after)))
                self.close(consume)
                self.assertIn(expected,self.code(store))

    def test_matching_unequip_input_blocks_generation_even_for_delayed_reply(self):
        for requested in (False,True):
            _,store,consume=self.setup_store(gear=True)
            if requested:
                consume(packet(0xab,struct.pack('<H',2),direction='SEND'))
                for _ in range(30):consume(packet(0xffff))
            consume(packet(0x99a,struct.pack('<HIB',2,2,0)))
            self.close(consume)
            self.assertEqual(any(line=='unequip 4;' for line in self.code(store).splitlines()),not requested)

    def test_own_sit_and_stand_require_no_matching_input_and_ignore_other_players(self):
        for action in (2,3):
            for requested in (False,True):
                _,store,consume=self.setup_store()
                if requested:consume(packet(0x89,struct.pack('<IB',0,action),direction='SEND'))
                body=bytearray(27);struct.pack_into('<I',body,0,777);body[24]=action
                consume(packet(0x8a,body))
                struct.pack_into('<I',body,0,888)
                consume(packet(0x8a,body))
                self.close(consume)
                command='sit;' if action==2 else 'stand;'
                self.assertEqual(self.code(store).splitlines().count(command),0 if requested else 1)

    def test_dropitem_excludes_mob_death_and_manual_drop_and_does_not_invent_lifetime(self):
        for cause in ('none','death','drop'):
            _,store,consume=self.setup_store()
            store.commands.policy['dropitem_lifetime_ms']=None
            consume(packet(0x85,bytes(3),direction='SEND'))
            if cause=='death':
                consume(actor_packet(actor_id=55,actor_type=5))
                consume(packet(0x80,struct.pack('<IB',55,1)))
            if cause=='drop':consume(packet(0xa2,struct.pack('<HH',2,1),direction='SEND'))
            body=bytearray(22)
            struct.pack_into('<II',body,0,900,501)
            struct.pack_into('<HH',body,11,100,120)
            struct.pack_into('<H',body,17,3)
            consume(packet(0xadd,body))
            self.close(consume)
            code=self.code(store)
            drops=[r for r in store.commands.observations if r['fields']['command']=='dropitem']
            self.assertEqual(len(drops),int(cause=='none'))
            if cause=='none':
                self.assertIn('// dropitem "test.gat",100,120,501,3,__EXTRA_LIFETIME_MS__;',code)
                self.assertIsNone(drops[0]['fields']['arguments']['extra_lifetime_ms'])

    def test_waitingroom_is_oninit_only_and_observation_filter_is_owner_specific(self):
        from parser.ignorepacket import IgnorePacket,observation_tags
        world,store,consume=self.setup_store()
        def room(actor):
            body=struct.pack('<IIHHB',actor,700,0,0,1)+b'Queue\0'
            raw=struct.pack('<HH',0xd7,len(body)+4)+body
            return replace(packet(0xd7),raw=raw)
        consume(room(42));self.close(consume)
        code=self.code(store)
        self.assertEqual(code.count('waitingroom "Queue",0;'),1)
        self.assertLess(code.index('OnInit:'),code.index('waitingroom "Queue",0;'))
        self.assertTrue(IgnorePacket().hides(room(42),observation_tags(replace(room(42),connection='game',flow_id='game'),world,0)))
        self.assertFalse(IgnorePacket().hides(room(888),observation_tags(replace(room(888),connection='game',flow_id='game'),world,0)))
        report=build_npc_bundle(world.snapshot('NPC')['entities'],[])
        self.assertIn('end;\n',report['auriga'].split('OnInit:')[0])
        self.assertIn('waitingroom "Queue",0;',report['auriga'])

    def test_sc_end_status_load_uses_conversion_table_inside_conversation(self):
        _,store,consume=self.setup_store()
        consume(packet(0x196,struct.pack('<HIB',10,777,0)))
        self.close(consume)
        self.assertIn('sc_end 10;',self.code(store))

    def test_storage_transfer_is_not_an_npc_reward_or_deletion(self):
        _,store,consume=self.setup_store()
        consume(packet(0xf2,struct.pack('<HH',0,600)))
        consume(pickup())
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        self.close(consume)
        code=self.code(store)
        self.assertIn('openstorage;',code)
        self.assertFalse(any(line.startswith(('getitem ','delitem ')) for line in code.splitlines()))

    def test_cart_transfer_is_not_an_npc_reward_or_deletion(self):
        _,store,consume=self.setup_store()
        consume(packet(0x127,struct.pack('<HI',9,50),direction='SEND'))
        consume(pickup(index=2,item_id=1010,amount=50))
        consume(packet(0x126,struct.pack('<HI',2,50),direction='SEND'))
        consume(packet(0x7fa,struct.pack('<HHH',0,2,50)))
        self.close(consume)
        code=self.code(store)
        self.assertFalse(any(line.startswith(('getitem ','getitem2 ','delitem ','delequip '))
                             for line in code.splitlines()))
        self.assertFalse(store.commands.observations)
        inventory=store.commands.states[(0,'game')]['inventory'][2]
        self.assertEqual((inventory['item_id'],inventory['amount']),(1010,0))

    def test_cart_transfer_regressions_keep_normal_rewards_and_leave_ambiguous_unresolved(self):
        # Request only / response only do not invent the other half.
        _,store,consume=self.setup_store()
        consume(packet(0x127,struct.pack('<HI',1,3),direction='SEND'))
        self.close(consume)
        self.assertFalse(store.commands.observations)
        _,store,consume=self.setup_store()
        consume(pickup(index=4,item_id=501,amount=3))
        self.close(consume)
        self.assertIn('getitem 501,3;',self.code(store))

        # Different amount than the cart request remains a normal reward.
        _,store,consume=self.setup_store()
        consume(packet(0x127,struct.pack('<HI',1,7),direction='SEND'))
        consume(pickup(index=5,item_id=502,amount=9))
        self.close(consume)
        self.assertIn('getitem 502,9;',self.code(store))
        self.assertEqual(len(store.commands.states[(0,'game')]['cart_to_body']),1)

        # Half-connection SEND/RECV still share flow-scoped cart state.
        _,store,consume=self.setup_store(split_connections=True)
        consume(packet(0x127,struct.pack('<HI',8,4),direction='SEND'))
        consume(pickup(index=6,item_id=503,amount=4))
        consume(packet(0x126,struct.pack('<HI',6,4),direction='SEND'))
        consume(packet(0x7fa,struct.pack('<HHH',0,6,4)))
        self.close(consume)
        self.assertFalse(any(line.startswith(('getitem ','delitem ')) for line in self.code(store).splitlines()))

        # Ambiguous same-amount cart withdrawals stay review-only, not executable.
        _,store,consume=self.setup_store()
        consume(packet(0x127,struct.pack('<HI',1,2),direction='SEND'))
        consume(packet(0x127,struct.pack('<HI',2,2),direction='SEND'))
        consume(pickup(index=7,item_id=504,amount=2))
        self.close(consume)
        code=self.code(store)
        self.assertIn('// getitem 504,2;',code)
        self.assertFalse(any(line.startswith('getitem ') for line in code.splitlines()))

        # Partial amount vs cart-from-body request stays unresolved review.
        _,store,consume=self.setup_store()
        consume(pickup(index=8,item_id=505,amount=10))
        consume(packet(0x126,struct.pack('<HI',8,10),direction='SEND'))
        consume(packet(0x7fa,struct.pack('<HHH',0,8,4)))
        self.close(consume)
        code=self.code(store)
        self.assertIn('getitem 505,10;',code)
        self.assertIn('// delitem 505,4;',code)
        self.assertFalse(any(line.startswith('delitem ') for line in code.splitlines()))

        # Late cart response after many unrelated packets still suppresses reward conversion.
        _,store,consume=self.setup_store()
        consume(packet(0x127,struct.pack('<HI',3,1),direction='SEND'))
        for _ in range(5):
            consume(dialogue_packet(0xb4,struct.pack('<I',42)+b'x\0'))
        consume(pickup(index=9,item_id=506,amount=1))
        self.close(consume)
        self.assertFalse(any(line.startswith('getitem ') for line in self.code(store).splitlines()))

        # Normal NPC reward/deletion without cart SEND still emits.
        _,store,consume=self.setup_store()
        consume(pickup(index=2,item_id=507,amount=1))
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        self.close(consume)
        code=self.code(store)
        self.assertIn('getitem 507,1;',code)
        self.assertIn('delitem 507,1;',code)

        # Storage suppression remains independent of cart handling.
        _,store,consume=self.setup_store()
        consume(packet(0xf2,struct.pack('<HH',0,600)))
        consume(packet(0x127,struct.pack('<HI',4,1),direction='SEND'))
        consume(pickup(index=3,item_id=508,amount=1))
        self.close(consume)
        self.assertIn('openstorage;',self.code(store))
        self.assertFalse(any(line.startswith('getitem ') for line in self.code(store).splitlines()))

    def test_cutincard_is_not_generated_and_original_cutin_is_preserved(self):
        _,store,consume=self.setup_store()
        consume(packet(0x1b3,b'card_picture'.ljust(64,b'\0')+bytes([4])))
        self.close(consume)
        self.assertIn('cutin "card_picture",4;',self.code(store))
        self.assertNotIn('cutincard ',self.code(store))

    def test_storage_display_emits_only_open_transition_without_dialogue(self):
        from parser.display import ReceiveDisplay,DisplayProfile
        display=ReceiveDisplay(DisplayProfile.load())
        event=packet(0xf2,struct.pack('<HH',1,600))
        self.assertEqual(display.decode(event).text,'openstorage;')
        self.assertEqual(display.decode(event,timestamp=True).text,'')
        display.decode(packet(0xf8))
        self.assertEqual(display.decode(event).text,'openstorage;')

    def test_openstorage_after_close_reply_is_close2_and_timeout_close_does_not_resume(self):
        for timeout in (False,True):
            _,store,consume=self.setup_store()
            if timeout:consume(packet(0xb5,struct.pack('<I',42)))
            self.close(consume)
            consume(packet(0x146,struct.pack('<I',42),direction='SEND'))
            consume(packet(0xf2,struct.pack('<HH',1,600)))
            code=self.code(store)
            self.assertEqual('close2;' in code,not timeout)
            self.assertEqual(any(line=='openstorage;' for line in code.splitlines()),not timeout)

    def test_configured_drop_time_is_explicit_and_later_death_suppresses_candidate(self):
        _,store,consume=self.setup_store()
        store.commands.policy['dropitem_lifetime_ms']=60000
        consume(packet(0x85,bytes(3),direction='SEND'))
        consume(actor_packet(actor_id=55,actor_type=5))
        body=bytearray(22);struct.pack_into('<II',body,0,900,501)
        struct.pack_into('<HH',body,11,100,120);struct.pack_into('<H',body,17,3)
        consume(packet(0xadd,body))
        self.assertTrue(any(line=='dropitem "test.gat",100,120,501,3,0;' for line in self.code(store).splitlines()))
        self.assertIn('総寿命は指定値60000ms',self.code(store))
        consume(packet(0x80,struct.pack('<IB',55,1)))
        self.assertFalse(any(line.startswith('dropitem ') for line in self.code(store).splitlines()))
        self.assertTrue(store.commands.observations[-1]['fields']['review_only'])

    def test_unrelated_item_gain_after_closed_dialogue_is_not_a_continuation(self):
        _,store,consume=self.setup_store()
        self.close(consume)
        consume(packet(0x146,struct.pack('<I',42),direction='SEND'))
        consume(pickup())
        code=self.code(store)
        self.assertNotIn('close2;',code)
        self.assertFalse(any(line.startswith('getitem ') for line in code.splitlines()))

    def test_command_observation_capacity_is_reported_without_claiming_complete_dialogue(self):
        _,store,consume=self.setup_store()
        store.commands.observations=[{}]*10000
        consume(packet(0xf2,struct.pack('<HH',1,600)))
        self.assertEqual(len(store.commands.observations),10000)
        self.assertEqual(store.commands.dropped,1)
        self.assertTrue(store.sessions[0].issues)

    def test_dropitem_total_lifetime_subtracts_the_configured_base(self):
        _,store,consume=self.setup_store()
        store.commands.policy['dropitem_lifetime_ms']=60000
        store.commands.policy['flooritem_base_lifetime_ms']=120000
        consume(packet(0x85,bytes(3),direction='SEND'))
        body=bytearray(22);struct.pack_into('<II',body,0,900,501)
        struct.pack_into('<HH',body,11,100,120);struct.pack_into('<H',body,17,3)
        consume(packet(0xadd,body))
        self.assertIn('dropitem "test.gat",100,120,501,3,-60000;',self.code(store))
        self.assertIn('基本寿命120000ms',self.code(store))

    def test_dropitem_uses_instance_map_reference_without_changing_raw_name(self):
        fields=dict(command='dropitem',arguments=dict(map_name='0k81@toy.gat',x=10,y=20,item_id=501,amount=1,extra_lifetime_ms=0),
                    review_only=False,reason='',lifetime_ms=60000,base_lifetime_ms=60000)
        before=deepcopy(fields)
        code=render_command(fields,AurigaRenderer().templates)
        self.assertIn('dropitem getmdmapname("1@toy.gat"),10,20,501,1,0;',code)
        self.assertEqual(fields,before)

    def test_bidirectional_halves_share_request_and_storage_state_by_flow(self):
        _,store,consume=self.setup_store(gear=True,split_connections=True)
        consume(packet(0xab,struct.pack('<H',2),direction='SEND'))
        consume(packet(0x99a,struct.pack('<HIB',2,2,0)))
        consume(packet(0xf2,struct.pack('<HH',1,600)))
        consume(packet(0x89,struct.pack('<IB',0,2),direction='SEND'))
        consume(packet(0xf2,struct.pack('<HH',2,600)))
        self.close(consume)
        code=self.code(store)
        self.assertFalse(any(line=='unequip 4;' for line in code.splitlines()))
        self.assertEqual(code.splitlines().count('openstorage;'),1)

    def test_reused_inventory_index_does_not_borrow_previous_equipment_slot(self):
        _,store,consume=self.setup_store(gear=True)
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        event=pickup(index=2,item_id=1102,amount=1)
        raw=bytearray(event.raw);raw[32]=4
        consume(replace(event,raw=bytes(raw)))
        consume(packet(0x188,struct.pack('<HHH',0,2,8)))
        self.close(consume)
        code=self.code(store)
        self.assertFalse(any(line.startswith('successrefitem ') for line in code.splitlines()))
        self.assertIn('// successrefitem __SLOT__;',code)
