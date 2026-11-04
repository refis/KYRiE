from tests.support.player import packet, listing, pickup
from dataclasses import replace
import struct
import unittest

from reconstruction.player import PlayerStore, LIST_STRIDES, IDENTIFY_FLAG_OFFSETS, decode_player
from reconstruction.decoder import ObservationError
from parser.display import DisplayProfile, ReceiveDisplay
from tests.support.world import actor_packet, map_packet








class PlayerTests(unittest.TestCase):
    def test_account_bound_maps_and_latest_login_keep_character_values_and_evidence_separate(self):
        from tests.support.player import character_list
        def char_login(store, account, flow):
            store.apply(packet(0x65, struct.pack('<I', account) + bytes(11), direction='SEND', flow=flow))
        def hint(store, name, flow):
            store.apply(packet(0x71, struct.pack('<I', 123) + name.encode().ljust(16, b'\0') + bytes(6), flow=flow))
        def login(store, account, flow):
            store.apply(packet(0x436, struct.pack('<II', account, 123) + bytes(13), direction='SEND', flow=flow))
            return store.states[(0, flow)]
        store = PlayerStore()
        char_login(store, 42, 'char-a'); hint(store, 'a.gat', 'char-a')
        char_login(store, 99, 'char-b'); hint(store, 'b.gat', 'char-b')
        self.assertIsNone(login(store, 77, 'wrong').map_name)
        self.assertEqual(login(store, 42, 'a').map_name, 'a.gat')
        self.assertEqual(login(store, 99, 'b').map_name, 'b.gat')
        unknown = PlayerStore()
        hint(unknown, 'a.gat', 'unbound-a'); hint(unknown, 'b.gat', 'unbound-b')
        self.assertIsNone(login(unknown, 42, 'game').map_name)
        unknown.apply(character_list())
        unknown.apply(replace(character_list(name='other'), flow_id='other', connection='other'))
        self.assertEqual(len(unknown.characters), 2)

        store = PlayerStore()
        char_login(store, 42, 'char')
        store.apply(character_list(), packet_index=10)
        login(store, 42, 'old')
        store.apply(packet(0xb1, struct.pack('<HI', 20, 1200), flow='old'), packet_index=12)
        current = login(store, 42, 'new')
        self.assertEqual((current.zeny, current.evidence['zeny']['packet_index']), (1200, 12))
        store.apply(packet(0xb1, struct.pack('<HI', 20, 900), flow='old'), packet_index=14)
        self.assertEqual(store.states[(0, 'old')].zeny, 900)
        self.assertEqual(store.characters[(42, 123)]['zeny'], 1200)
        store.apply(packet(0xb1, struct.pack('<HI', 20, 1300), flow='new'), packet_index=15)
        store.apply(character_list(zeny=1400), packet_index=16)
        saved = store.characters[(42, 123)]
        self.assertEqual((saved['zeny'], saved['evidence']['zeny']['packet_index']), (1400, 16))
        body = b'new-map.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20) + bytes(6)
        store.apply(packet(0x92, body, flow='new'))
        body = b'old-map.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20) + bytes(6)
        store.apply(packet(0x92, body, flow='old'))
        self.assertEqual(login(store, 42, 'third').map_name, 'new-map.gat')

    def test_character_catalog_seeds_matching_login_and_updates_zeny_and_exp(self):
        from tests.support.player import character_list
        for pid in (0x99d, 0xb72):
            with self.subTest(pid=pid):
                store = PlayerStore()
                login = packet(0x65, struct.pack('<I', 42) + bytes(11), flow='char', direction='SEND')
                store.apply(login, packet_index=0)
                listing = character_list(pid)
                store.apply(listing, packet_index=1)
                store.apply(packet(pid, b'', flow='char'))
                self.assertEqual(len(store.characters), 1)
                store.apply(packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND'))
                state = store.states[(0, 'game')]
                self.assertEqual((state.character_name, state.zeny, state.base_exp, state.job_exp),
                                 ('hero', 1000, 2**40, 2**41))
                store.apply(packet(0xb1, struct.pack('<HI', 20, 1200)), packet_index=3)
                store.apply(packet(0xacb, struct.pack('<HQ', 1, 2**42)), packet_index=4)
                store.apply(packet(0xacb, struct.pack('<HQ', 2, 2**43)), packet_index=5)
                self.assertEqual(state.zeny_delta, 200)
                saved = store.snapshot()['characters'][0]
                self.assertEqual((saved['zeny'], saved['base_exp'], saved['job_exp']), (1200, 2**42, 2**43))
                self.assertEqual(saved['evidence']['zeny']['packet_index'], 3)
                saved['evidence']['zeny']['packet_index'] = -1
                self.assertEqual(store.characters[(42, 123)]['evidence']['zeny']['packet_index'], 3)
                store.apply(packet(0x436, struct.pack('<II', 99, 123) + bytes(13), flow='other', direction='SEND'))
                self.assertIsNone(store.states[(0, 'other')].character_name)
                raw = bytearray(listing.raw)
                struct.pack_into('<H', raw, 2, len(raw) - 1)
                store.apply(replace(listing, raw=bytes(raw)))
                self.assertEqual(store.issue_count, 1)
                self.assertEqual(store.characters[(42, 123)]['zeny'], 1200)
                name_offset = 112 if pid == 0xb72 else 92
                raw = bytearray(listing.raw)
                raw[name_offset:name_offset + 24] = b'\x81\0' + bytes(22)
                store.apply(replace(listing, raw=bytes(raw)))
                self.assertEqual(store.issue_count, 2)
                self.assertEqual(store.characters[(42, 123)]['character_name'], 'hero')
                self.assertEqual(store.characters[(42, 123)]['zeny'], 1000)
                store.apply(packet(pid, listing.raw[4:] * 2, flow='char'))
                self.assertEqual(store.issue_count, 3)
                unbound = PlayerStore()
                unbound.apply(listing)
                unbound.apply(packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND'))
                self.assertIsNone(unbound.states[(0, 'game')].character_name)
                store.apply(login, session=1)
                self.assertFalse(store.characters)

    def test_map_login_sex_uses_declared_layout_and_rejects_unsupported_values(self):
        from reconstruction.player import decode_player
        from reconstruction.decoder import ObservationError
        from parser.display import DEFAULT_SEND_PROFILE
        display = ReceiveDisplay(DisplayProfile.load(DEFAULT_SEND_PROFILE), direction='SEND')
        for pid, size in ((0x72, 19), (0x436, 23)):
            raw = bytearray(size)
            struct.pack_into('<HII', raw, 0, pid, 42, 123)
            if pid == 0x436:
                raw[18] = 169
            raw[-1] = 0
            event = replace(packet(pid, direction='SEND'), raw=bytes(raw))
            self.assertEqual(decode_player(event)[1]['sex'], 0)
            self.assertIn('sex=0', display.decode(event).text)
            raw[-1] = 2
            with self.assertRaises(ObservationError):
                decode_player(replace(event, raw=bytes(raw)))
            self.assertEqual(display.decode(replace(event, raw=bytes(raw))).status, 'error')
        with self.assertRaises(ObservationError):
            decode_player(packet(0x436, struct.pack('<II', 42, 123) + bytes(9), direction='SEND'))

    def setUp(self):
        self.store = PlayerStore()

    def state(self):
        return self.store.states[(0, 'game')]

    def snapshot(self, entries=((2, 501, 10),)):
        self.store.apply(packet(0xb08, b'\0'))
        self.store.apply(listing(items=entries))
        self.store.apply(listing(0xb39, ((3, 1201, 1),)))
        self.store.apply(packet(0xb0b, b'\0\0'))

    def test_split_snapshot_empty_snapshot_and_replacement(self):
        self.snapshot()
        self.assertEqual(len(self.state().items), 2)
        self.assertEqual(self.state().total_amount, 11)
        self.assertTrue(self.state().inventory_complete)
        self.store.apply(packet(0xb08, b'\0'))
        self.assertFalse(self.state().inventory_complete)
        self.store.apply(packet(0xb0b, b'\0\0'))
        self.assertEqual(self.state().items, {})
        self.assertTrue(self.state().inventory_complete)

    def test_all_supported_list_strides(self):
        for pid in LIST_STRIDES:
            store = PlayerStore()
            store.apply(listing(pid))
            state = next(iter(store.states.values()))
            self.assertEqual(state.items[2]['amount'], 10 if pid in (0xb09, 0xb38) else 1)
            self.assertFalse(state.inventory_complete)

    def test_inventory_success_failure_and_removal(self):
        self.snapshot()
        self.store.apply(pickup())
        self.assertEqual(self.state().items[2]['amount'], 13)
        self.store.apply(pickup(result=255))
        self.assertEqual(self.state().items[2]['amount'], 13)
        self.store.apply(packet(0xaf, struct.pack('<HH', 2, 3)))
        self.assertEqual(self.state().items[2]['amount'], 10)
        self.store.apply(packet(0x7fa, struct.pack('<HHH', 0, 2, 10)))
        self.assertNotIn(2, self.state().items)
        self.assertTrue(self.state().inventory_complete)

    def test_bad_counts_unknown_slot_and_changed_item_do_not_invent_inventory(self):
        for invalid in (packet(0xaf, struct.pack('<HH', 999, 1)),
                        packet(0xaf, struct.pack('<HH', 2, 11)), pickup(item_id=502)):
            self.store = PlayerStore()
            self.snapshot()
            before = dict(self.state().items)
            result = self.store.apply(invalid)
            self.assertIn('observation_error', result)
            self.assertEqual(self.state().items, before)
            self.assertFalse(self.state().inventory_complete)

    def test_invalid_snapshot_is_atomic_and_storage_is_excluded(self):
        self.snapshot()
        self.store.apply(packet(0xb08, b'\0'))
        malformed = packet(0xb09, b'\0' + bytes(33))
        self.store.apply(malformed)
        self.store.apply(packet(0xb0b, b'\0\0'))
        self.assertEqual(self.state().total_amount, 11)
        self.assertFalse(self.state().inventory_complete)
        self.store.apply(listing(items=((8, 999, 1),), inventory_type=2))
        self.store.apply(packet(0xb0b, b'\x02\0'))
        self.assertNotIn(8, self.state().items)

    def test_duplicate_slots_and_capacity_fail_closed(self):
        self.store = PlayerStore(max_slots=1)
        self.store.apply(packet(0xb08, b'\0'))
        self.store.apply(listing(items=((2, 501, 10), (3, 502, 2))))
        self.assertFalse(self.state().items)
        self.assertEqual(self.store.issue_count, 1)
        self.store = PlayerStore()
        self.store.apply(packet(0xb08, b'\0'))
        self.store.apply(listing())
        self.store.apply(listing())
        self.assertEqual(self.store.issue_count, 1)
        self.assertFalse(self.state().inventory_complete)

    def test_complementary_ammunition_lists_keep_only_received_normal_quantity(self):
        for normal_pid, equipment_pid in ((0xb09, 0xb39), (0xb38, 0xb0a)):
            for reverse in (False, True):
                with self.subTest(normal=normal_pid, equipment=equipment_pid, reverse=reverse):
                    self.store = PlayerStore(max_slots=1)
                    self.store.apply(packet(0xb08, b'\0'))
                    records = [listing(normal_pid, items=((132, 1751, 601),), item_type=10),
                               listing(equipment_pid, items=((132, 1751, 1),), item_type=10)]
                    for event in reversed(records) if reverse else records:
                        self.store.apply(event)
                    self.store.apply(packet(0xb0b, b'\0\0'))
                    self.assertEqual(self.state().items[132]['item_id'],1751)
                    self.assertEqual(self.state().items[132]['amount'],601)
                    self.assertTrue(self.state().inventory_complete)
                    self.assertEqual(self.store.issue_count, 0)
                    self.store.apply(packet(0x7fa, struct.pack('<HHH', 0, 132, 1)))
                    self.assertEqual(self.state().items[132]['amount'], 600)

    def test_ammunition_without_quantity_or_with_conflicting_duplicates_fails_closed(self):
        normal = listing(items=((132, 1751, 601),), item_type=10)
        equip = listing(0xb39, items=((132, 1751, 1),), item_type=10)
        cases = [(equip,), (normal, normal),
                 (normal, listing(0xb39, items=((132, 1752, 1),), item_type=10)),
                 (normal, listing(0xb39, items=((132, 1751, 1),), item_type=11)),
                 (normal, equip, equip)]
        for events in cases:
            with self.subTest(events=len(events)):
                self.store = PlayerStore()
                self.snapshot()
                before = dict(self.state().items)
                self.store.apply(packet(0xb08, b'\0'))
                for event in events:
                    self.store.apply(event)
                self.store.apply(packet(0xb0b, b'\0\0'))
                self.assertGreater(self.store.issue_count, 0)
                self.assertFalse(self.state().inventory_complete)
                self.assertEqual(self.state().items, before)

    def test_zeny_baseline_positive_and_negative_changes_are_flow_scoped(self):
        first = self.store.apply(packet(0xb1, struct.pack('<HI', 20, 1000)))
        self.assertFalse(first['delta_known'])
        self.assertEqual(self.store.apply(packet(0xb1, struct.pack('<HI', 20, 1300)))['delta'], 300)
        self.assertEqual(self.store.apply(packet(0xb1, struct.pack('<HI', 20, 900)))['delta'], -400)
        self.store.apply(packet(0xb1, struct.pack('<HI', 20, 10), flow='other'))
        self.assertEqual(self.state().zeny, 900)
        self.assertIsNone(self.store.states[(0, 'other')].zeny_delta)
        self.store.begin_capture(1)
        self.store.apply(packet(0xb1, struct.pack('<HI', 20, 999)), session=0)
        self.assertFalse(self.store.states)

    def test_map_position_walking_destination_and_other_unit_fix(self):
        self.store.apply(packet(0x283, struct.pack('<I', 42)))
        self.store.apply(replace(map_packet(), flow_id='game'))
        packed = bytes([10 >> 2, ((10 & 3) << 6) | (20 >> 4), ((20 & 15) << 4) | (30 >> 6),
                        ((30 & 63) << 2) | (40 >> 8), 40, 0])
        self.store.apply(packet(0x87, bytes(4) + packed))
        self.assertEqual((self.state().x, self.state().y), (10, 20))
        self.assertEqual((self.state().destination_x, self.state().destination_y), (30, 40))
        self.store.apply(packet(0x88, struct.pack('<IHH', 999, 99, 99)))
        self.assertEqual(self.state().x, 10)
        self.store.apply(packet(0x88, struct.pack('<IHH', 42, 30, 40)))
        self.assertEqual(self.state().x, 30)
        self.assertIsNone(self.state().destination_x)

    def test_selected_map_hint_requires_matching_character_login(self):
        self.store.apply(packet(0x71, struct.pack('<I', 123) + b'test.gat'.ljust(16, b'\0') + bytes(6), flow='char'))
        self.store.apply(packet(0x436, struct.pack('<II', 42, 999) + bytes(13), direction='SEND'))
        self.assertIsNone(self.state().map_name)
        self.store.apply(packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND', flow='map2'))
        self.assertEqual(self.store.states[(0, 'map2')].map_name, 'test.gat')

    def test_explicit_login_resets_unidentified_balance_and_state_capacity_is_bounded(self):
        self.store.apply(packet(0xb1, struct.pack('<HI', 20, 1000)))
        self.store.apply(packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND'))
        self.assertIsNone(self.state().zeny)
        self.store = PlayerStore(max_states=1)
        self.store.apply(packet(0xb08, b'\0'))
        self.store.apply(packet(0xb1, struct.pack('<HI', 20, 1000), flow='other'))
        self.assertEqual(len(self.store.states), 1)
        self.assertFalse(self.store.pending)

    def test_display_actor_first_appearance_movement_inventory_and_zeny(self):
        display = ReceiveDisplay(DisplayProfile.load())
        actor = actor_packet(actor_type=5)
        first = display.decode(actor)
        self.assertIn('MOB 初回観測', first.text)
        self.assertEqual((first.fields['x'], first.fields['y']), (150, 200))
        self.assertNotIn('初回観測', display.decode(actor).text)
        self.assertIn('移動', display.decode(actor_packet(actor_type=5, pid=0x9fd)).text)
        walk = ReceiveDisplay(DisplayProfile.load())
        first_walk = walk.decode(actor_packet(actor_type=12, pid=0x9fd, name='歩行NPC'))
        self.assertIn('NPC(歩行型) 初回観測/移動', first_walk.text)
        self.assertNotIn('npcwalkto', first_walk.text)
        moved = walk.decode(actor_packet(actor_type=12, pid=0x9fd, name='歩行NPC',
                                         x=160, y=210, destination=(301, 402), timestamp=2.0))
        self.assertIn('npcwalkto 301,402,"歩行NPC";', moved.text)
        self.assertIn('// 歩行NPC(42), 160, 210: speed:150', moved.text)
        self.assertIn('npcwalkwait 50,"歩行NPC";', moved.text)
        self.assertIn('walk≈37310ms', moved.text)
        self.assertLess(moved.text.index('npcwalkto'), moved.text.index('npcwalkwait'))
        speed = ReceiveDisplay(DisplayProfile.load())
        appear = speed.decode(actor_packet(actor_type=12, pid=0x9fe, name='歩行NPC'))
        self.assertIn('setnpcspeed 150,"歩行NPC";', appear.text)
        idle = speed.decode(actor_packet(actor_type=12, pid=0x9ff, name='歩行NPC', timestamp=2.0))
        self.assertIn('setnpcspeed 150,"歩行NPC";', idle.text)
        self.assertIn('歩行NPC(42)', idle.text)
        self.assertIn('差分不明', display.decode(packet(0xb1, struct.pack('<HI', 20, 1000))).text)
        self.assertIn('Zeny -200', display.decode(packet(0xb1, struct.pack('<HI', 20, 800))).text)
        # HP/SP etc. update_status lines are suppressed; Zeny/EXP remain.
        self.assertEqual(display.decode(packet(0xb0, struct.pack('<HI', 5, 200))).text, '')
        self.assertIn('@BaseExp', display.decode(packet(0xb0, struct.pack('<HI', 1, 12345))).text)
        self.assertIn('getitem 501,3;', display.decode(pickup()).text)
        self.assertIn('delitem 501,2;', display.decode(packet(0xaf, struct.pack('<HH', 2, 2))).text)
        self.assertNotIn('getitem 501', display.decode(pickup(result=255)).text)
        decorated = pickup()
        raw = bytearray(decorated.raw)
        raw[68] = 7
        result = display.decode(replace(decorated, raw=bytes(raw)))
        self.assertIn('refine=7', result.text)
        self.assertNotIn('getitem 501', result.text)
        partial = display.decode(actor_packet(actor_type=6, raw_name=b'\x81'))
        self.assertEqual(partial.status, 'decoded')
        self.assertFalse(partial.fields['name_valid'])
        self.assertIn('名前解読不可', partial.text)
        self.assertIn('XY=(150,200)', partial.text)



    def test_inventory_identification_uses_bit_zero_and_preserves_other_flag_bits(self):
        for pid,offset in ((0xb09,33),(0xb0a,66),(0xb39,67)):
            for flags in (0,1,2,3,0x80,0x81,0xff):
                with self.subTest(pid=pid,flags=flags):
                    store=PlayerStore();store.apply(packet(0xb08,b'\0'))
                    event=listing(pid);raw=bytearray(event.raw);raw[5+offset]=flags
                    store.apply(replace(event,raw=bytes(raw)))
                    store.apply(packet(0xb0b,b'\0\0'))
                    item=store.states[(0,'game')].items[2]
                    self.assertEqual(item['identified'],bool(flags&1))
                    self.assertEqual(item['inventory_flags'],flags)
                    self.assertEqual(item['identification_packet_id'],pid)
        for pid in (0xb38,):
            store=PlayerStore();store.apply(listing(pid))
            self.assertIsNone(store.states[(0,'game')].items[2]['identified'])

    def test_inventory_list_identify_boundary_keeps_unconfirmed_0b38_unstructured(self):
        from pathlib import Path
        from parser.definitions import load_lengths
        lengths = load_lengths(Path(__file__).resolve().parents[2] / 'PacketLength.txt')
        # Live framing has no 0B38 entry (0B37 then 0B39); do not invent a length.
        self.assertNotIn(0xb38, lengths)
        self.assertIn(0xb37, lengths)
        self.assertIn(0xb39, lengths)
        self.assertEqual(LIST_STRIDES, {0xb09: 34, 0xb0a: 67, 0xb38: 35, 0xb39: 68})
        self.assertEqual(IDENTIFY_FLAG_OFFSETS, {0xb09: 33, 0xb0a: 66, 0xb39: 67})
        self.assertNotIn(0xb38, IDENTIFY_FLAG_OFFSETS)
        for pid, offset in IDENTIFY_FLAG_OFFSETS.items():
            self.assertLess(offset, LIST_STRIDES[pid])
        store = PlayerStore()
        store.apply(listing(0xb38))
        item = store.states[(0, 'game')].items[2]
        self.assertIsNone(item['identified'])
        self.assertIsNone(item['inventory_flags'])
        # Wrong stride / length must fail closed; never reinterpret as another confirmed layout.
        bad = listing(0xb09)
        with self.assertRaises(ObservationError):
            decode_player(replace(bad, raw=bad.raw[:-1]))
        # Normal shop product rows (00C6) are outside player inventory decode.
        self.assertIsNone(decode_player(packet(0xc6, struct.pack('<IIBI', 100, 76, 0, 501))))

    def test_pickup_identification_and_success_ack_do_not_change_observed_quantity(self):
        store=PlayerStore();event=pickup();raw=bytearray(event.raw);raw[10]=0
        store.apply(replace(event,raw=bytes(raw)))
        state=store.states[(0,'game')]
        self.assertIs(state.items[2]['identified'],False)
        store.apply(packet(0xaf,struct.pack('<HH',2,1)))
        self.assertIs(state.items[2]['identified'],False)
        store.apply(packet(0x179,struct.pack('<HB',2,1)))
        self.assertIs(state.items[2]['identified'],False)
        store.apply(packet(0x179,struct.pack('<HB',2,0)))
        self.assertIs(state.items[2]['identified'],True)
        self.assertEqual(state.items[2]['amount'],2)
        self.assertEqual(state.items[2]['identification_packet_id'],0x179)
        store.apply(packet(0x179,struct.pack('<HB',999,0)))
        self.assertNotIn(999,state.items)
        self.assertEqual(store.issue_count,1)


if __name__ == '__main__':
    unittest.main()

