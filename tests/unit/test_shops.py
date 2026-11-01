import struct
import unittest

from events import PacketEvent
from reconstruction.dialogue import DialogueStore
from reconstruction.shops import ShopStore, decode_shop_list
from reconstruction.decoder import ObservationError


def message(pid, body=b'', direction='RECV', flow='game', timestamp=1):
    raw = struct.pack('<H', pid)
    if pid in (0xb4, 0xb7, 0xc6, 0xb77):
        raw += struct.pack('<H', len(body) + 4)
    return PacketEvent(timestamp, direction, pid, raw + body, 'NPCAP', 'half', flow)


class ShopTests(unittest.TestCase):
    def test_supported_lists_keep_u32_ids_and_both_prices(self):
        old = message(0xc6, struct.pack('<IIBI', 100, 76, 3, 70000))
        modern = message(0xb77, struct.pack('<IIIBHI', 70000, 100, 76, 3, 42, 16))
        for event in (old, modern):
            item = decode_shop_list(event)[0]
            self.assertEqual((item['client_item_id'], item['price'], item['discount_price']), (70000, 100, 76))
        self.assertEqual(decode_shop_list(modern)[0]['location'], 16)
        for event in (message(0xc6, b'x'), message(0xc6, struct.pack('<IIBI', 1, 1, 0, 0)),
                      message(0xc6, struct.pack('<IIBH', 1, 1, 0, 501)),
                      message(0xc6, struct.pack('<IIBI', 1, 1, 0, 501) * 2049)):
            with self.assertRaises(ObservationError):
                decode_shop_list(event)

    def test_target_association_consumption_timeout_scope_and_cancel(self):
        listing = message(0xc6, struct.pack('<IIBI', 100, 76, 3, 501))
        store = ShopStore()
        store.apply(message(0xc4, struct.pack('<I', 42)), packet_index=1)
        store.apply(message(0xc5, struct.pack('<IB', 42, 0), 'SEND'), packet_index=2)
        store.apply(listing, packet_index=3)
        self.assertEqual(store.records[0]['actor_id'], 42)
        self.assertEqual(store.records[0]['association'], 'selector_and_buy_reply')
        self.assertEqual(len(store.records[0]['association_evidence']), 2)
        store.apply(listing)
        self.assertIsNone(store.records[-1]['actor_id'])
        for cancellation in (message(0xc5, struct.pack('<IB', 42, 1), 'SEND'),
                             message(0xc5, struct.pack('<IB', 99, 0), 'SEND'),
                             message(0x91), message(0x146, direction='SEND'),
                             message(0x80, struct.pack('<IB', 42, 0))):
            store.apply(message(0xc4, struct.pack('<I', 42)))
            store.apply(cancellation)
            store.apply(listing)
            self.assertIsNone(store.records[-1]['actor_id'])
        store.apply(message(0xc4, struct.pack('<I', 42)))
        store.apply(message(0xc6, struct.pack('<IIBI', 100, 76, 3, 501), flow='other'))
        self.assertIsNone(store.records[-1]['actor_id'])
        store.apply(message(0xc6, struct.pack('<IIBI', 100, 76, 3, 501), timestamp=62))
        self.assertIsNone(store.records[-1]['actor_id'])
        store.apply(message(0xc4, struct.pack('<I', 42)))
        store.apply(listing, session=1)
        self.assertIsNone(store.records[-1]['actor_id'])
        from reconstruction.world import WorldStore
        from tests.support.world import actor_packet
        from dataclasses import replace
        world = WorldStore()
        delayed = ShopStore(world)
        delayed.apply(message(0xc4, struct.pack('<I', 42)))
        world.apply(replace(actor_packet(), connection='half', flow_id='game'))
        delayed.apply(listing)
        self.assertEqual(delayed.records[0]['actor_id'], 42)
        self.assertFalse(delayed.records[0]['npc'])

    def test_after_close_list_links_without_selector_inside_two_seconds(self):
        dialogues = DialogueStore()
        store = ShopStore(dialogues=dialogues)
        now = 1.0

        def consume(pid, body=b'', direction='RECV'):
            nonlocal now
            event = message(pid, body, direction, timestamp=now)
            index = dialogues.packet_ordinal
            store.apply(event, packet_index=index)
            dialogues.apply(event, packet_index=index)

        consume(0x90, struct.pack('<IB', 42, 1), 'SEND')
        consume(0xb4, struct.pack('<I', 42) + b'callshop\0')
        consume(0xb6, struct.pack('<I', 42))
        consume(0x146, struct.pack('<I', 42), 'SEND')
        now += 1.5
        consume(0xc6, struct.pack('<IIBI', 1200, 1200, 0, 1100006))
        self.assertEqual(store.records[0]['association'], 'after_close_list')
        self.assertEqual(store.records[0]['conversation_id'], dialogues.sessions[0].id)
        self.assertEqual(store.records[0]['conversation_link_basis'], 'same_flow_after_close')
        self.assertEqual(dialogues.sessions[0].status, 'shop_opened')
        self.assertEqual(dialogues.sessions[0].termination['packet_id'], 0xc6)

        dialogues2 = DialogueStore()
        store2 = ShopStore(dialogues=dialogues2)
        for event in (
                message(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=1.0),
                message(0xb4, struct.pack('<I', 42) + b'late\0', timestamp=1.0),
                message(0xb6, struct.pack('<I', 42), timestamp=1.0),
                message(0xc6, struct.pack('<IIBI', 1, 1, 0, 501), timestamp=4.0)):
            index = dialogues2.packet_ordinal
            store2.apply(event, packet_index=index)
            dialogues2.apply(event, packet_index=index)
        self.assertEqual(store2.records[0]['association'], 'unresolved')
        self.assertEqual(dialogues2.sessions[0].status, 'closed')

    def test_invalid_list_clears_target_and_capacity_is_not_silent(self):
        store = ShopStore(max_records=1)
        store.apply(message(0xc4, struct.pack('<I', 42)))
        store.apply(message(0xc6, b'private'))
        self.assertEqual(store.issue_count, 1)
        self.assertNotIn('private', str(list(store.issues)))
        listing = message(0xc6, struct.pack('<IIBI', 100, 76, 3, 501))
        store.apply(listing)
        self.assertIsNone(store.records[0]['actor_id'])
        store.apply(listing)
        self.assertEqual(len(store.records), 1)
        self.assertEqual(store.issue_count, 2)
        snapshot = store.snapshot()
        snapshot['records'][0]['items'][0]['price'] = 0
        self.assertEqual(store.records[0]['items'][0]['price'], 100)
