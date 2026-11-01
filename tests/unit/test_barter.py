import struct
import unittest

from events import PacketEvent
from reconstruction.barter import (
    BarterStore, decode_barterlist, decode_expanded_barter, decode_expanded_barter_b79)
from reconstruction.barter_export import BarterRenderer, format_barter_items, script_refine
from reconstruction.dialogue import DialogueStore
from reconstruction.decoder import ObservationError
from tests.support.branches import NPC


def message(pid, body=b'', direction='recv', flow='game', timestamp=1.0):
    direction = {'recv': 'RECV', 'send': 'SEND'}.get(direction, direction)
    if pid in (0xb0e, 0xb56, 0xb79):
        raw = struct.pack('<HH', pid, 4 + len(body)) + body
    else:
        raw = struct.pack('<H', pid)
        if pid in (0xb4, 0xb7):
            raw += struct.pack('<H', len(body) + 4)
        raw += body
    return PacketEvent(timestamp, direction, pid, raw, 'NPCAP', 'half', flow)


def barter_body(entries):
    """entries: (nameid, type, stock_or_neg1, zeny, [(currency_id, refine, amount, type)])"""
    chunks = [struct.pack('<I', len(entries))]
    for nameid, typ, stock, zeny, currencies in entries:
        amount = 0xffffffff if stock < 0 else stock
        chunks.append(struct.pack('<IHIIIII', nameid, typ, amount, 0, 0, zeny, len(currencies)))
        for currency_id, refine, currency_amount, currency_type in currencies:
            chunks.append(struct.pack('<IHIH', currency_id, refine, currency_amount, currency_type))
    return b''.join(chunks)


def barterlist_body(entries):
    """entries: (nameid, type, stock_or_neg1, currency_id, currency_amount, weight, index)"""
    chunks = []
    for nameid, typ, stock, currency_id, currency_amount, weight, index in entries:
        amount = 0xffffffff if stock < 0 else stock
        chunks.append(struct.pack('<I', nameid) + struct.pack('<B', typ) + struct.pack(
            '<IIIII', amount, currency_id, currency_amount, weight, index))
    return b''.join(chunks)


def b79_currency(chunks, currencies):
    for currency_id, refine, currency_amount, currency_type in currencies:
        chunks.append(struct.pack('<IHIH', currency_id, refine, currency_amount, currency_type))


def b79_body(entries, *, variant='20210203'):
    """entries: (nameid, type, stock, zeny, look, equip, refine_or_none, currencies)."""
    chunks = [struct.pack('<I', len(entries))]
    for nameid, typ, stock, zeny, look, equip, refine, currencies in entries:
        amount = 0xffffffff if stock < 0 else stock
        base = (struct.pack('<I', nameid) + struct.pack('<H', typ) + struct.pack('<I', amount)
                + struct.pack('<III', 0, 0, zeny) + struct.pack('<H', look) + struct.pack('<I', equip))
        if variant == '20210203':
            chunks.append(base + struct.pack('<I', len(currencies)))
            b79_currency(chunks, currencies)
        elif variant == '20250402':
            chunks.append(base + struct.pack('<II', refine if refine is not None else 0, len(currencies)))
            b79_currency(chunks, currencies)
        elif variant == '20260107':
            chunks.append(base + struct.pack('<II', len(currencies), refine if refine is not None else 0))
            b79_currency(chunks, currencies)
        else:
            raise ValueError(variant)
    return b''.join(chunks)


def observe_barter(*, gap=1.0, items=None, packet_id=0xb56, b79_variant='20260107'):
    """Close then barter list within the after-close window; returns record and conversation."""
    dialogues = DialogueStore()
    store = BarterStore(dialogues=dialogues)
    now = 1.0

    def consume(pid, body=b'', direction='recv'):
        nonlocal now
        event = message(pid, body, direction, timestamp=now)
        index = dialogues.packet_ordinal
        store.apply(event, packet_index=index)
        dialogues.apply(event, packet_index=index)

    consume(0x90, struct.pack('<IB', 42, 1), 'SEND')
    consume(0xb4, struct.pack('<I', 42) + b'barter path\0')
    consume(0xb6, struct.pack('<I', 42))
    consume(0x146, struct.pack('<I', 42), 'SEND')
    now += gap
    if packet_id == 0xb0e:
        entries = items or [(600014, 9, -1, 1000367, 8000, 3400, 0)]
        consume(0xb0e, barterlist_body(entries))
    elif packet_id == 0xb79:
        entries = items or [(450206, 4, -1, 0, 1, 0, 7, [(1000608, 0, 100, 3)])]
        consume(0xb79, b79_body(entries, variant=b79_variant))
    else:
        entries = items or [(450206, 4, -1, 0, [(1000608, 0, 100, 3)])]
        consume(0xb56, barter_body(entries))
    conversation = dialogues.sessions[0]
    conversation.npc = dict(NPC)
    return store.records[0], conversation


class BarterTests(unittest.TestCase):
    def test_decode_matches_callbarter_sample_and_rejects_trailing_bytes(self):
        body = barter_body([
            (450206, 4, -1, 0, [(1000608, 0, 100, 3)]),
            (101187, 2, -1, 0, [(1000608, 0, 100, 3)]),
        ])
        items = decode_expanded_barter(message(0xb56, body))
        self.assertEqual([row['client_item_id'] for row in items], [450206, 101187])
        self.assertEqual(items[0]['stock'], -1)
        self.assertEqual(items[0]['currencies'][0]['refine_level'], 0)
        self.assertEqual(format_barter_items(items),
                         '450206:-1:0 { 1000608:-1:100 },101187:-1:0 { 1000608:-1:100 }')
        self.assertEqual(script_refine(0), -1)
        self.assertEqual(script_refine(7), 7)
        with self.assertRaises(ObservationError):
            decode_expanded_barter(message(0xb56, body + b'\0\0'))

    def test_after_close_list_links_within_two_seconds_and_exports_commented_barter(self):
        record, conversation = observe_barter()
        self.assertEqual(record['association'], 'after_close_list')
        self.assertEqual(conversation.status, 'barter_opened')
        self.assertTrue(conversation.termination.get('after_close_barter'))
        code = BarterRenderer().render(record, item_ids_confirmed=True, conversation=conversation)
        self.assertIn('//-\tbarter\tGPA_B', code)
        self.assertIn('450206:-1:0 { 1000608:-1:100 }', code)
        self.assertIn('close2;', code)
        self.assertIn('// callbarter "', code)
        self.assertLess(code.index('//-\tbarter\t'), code.index('\tscript\t'))

        late_record, late_conversation = observe_barter(gap=3.0)
        self.assertEqual(late_record['association'], 'unresolved')
        self.assertEqual(late_conversation.status, 'closed')

    def test_decode_barterlist_0b0e_and_after_close_export(self):
        body = barterlist_body([
            (600014, 9, -1, 1000367, 8000, 3400, 0),
            (640014, 9, -1, 1000367, 8000, 2400, 1),
        ])
        items = decode_barterlist(message(0xb0e, body))
        self.assertEqual([row['client_item_id'] for row in items], [600014, 640014])
        self.assertEqual(items[0]['stock'], -1)
        self.assertEqual(items[0]['zeny'], 0)
        self.assertEqual(items[0]['currencies'][0]['client_item_id'], 1000367)
        self.assertEqual(items[0]['currencies'][0]['amount'], 8000)
        self.assertEqual(format_barter_items(items),
                         '600014:-1:0 { 1000367:-1:8000 },640014:-1:0 { 1000367:-1:8000 }')
        with self.assertRaises(ObservationError):
            decode_barterlist(message(0xb0e, body + b'\0'))

        record, conversation = observe_barter(packet_id=0xb0e)
        self.assertEqual(record['market_kind'], 'barterlist')
        self.assertEqual(record['association'], 'after_close_list')
        self.assertEqual(conversation.status, 'barter_opened')
        self.assertEqual(conversation.termination.get('market_kind'), 'barterlist')
        code = BarterRenderer().render(record, item_ids_confirmed=True, conversation=conversation)
        self.assertIn('//-\tbarter\tGPA_B', code)
        self.assertIn('600014:-1:0 { 1000367:-1:8000 }', code)
        self.assertIn('// callbarter "', code)

    def test_decode_0b79_layouts_and_after_close_export(self):
        sample = [(450206, 4, -1, 0, 1, 0, 7, [(1000608, 0, 100, 3)])]
        for variant, needle in (
                ('20260107', '20260107'),
                ('20250402', '20250402'),
                ('20210203', '20210203')):
            body = b79_body(sample, variant=variant)
            items, label = decode_expanded_barter_b79(message(0xb79, body))
            self.assertIn(needle, label)
            self.assertEqual(items[0]['client_item_id'], 450206)
            self.assertEqual(items[0]['view_sprite'], 1)
            self.assertEqual(items[0]['currencies'][0]['amount'], 100)
            if variant == '20210203':
                self.assertNotIn('refine_level', items[0])
            else:
                self.assertEqual(items[0]['refine_level'], 7)
            with self.assertRaises(ObservationError):
                decode_expanded_barter_b79(message(0xb79, body + b'\0\0'))

        # 20250402 writes refine=0; keep refine distinguishable via non-zero for 20260107 only.
        zero_refine = [(450206, 4, -1, 0, 1, 0, 0, [(1000608, 0, 100, 3)])]
        items, label = decode_expanded_barter_b79(message(0xb79, b79_body(zero_refine, variant='20250402')))
        self.assertIn('20250402', label)
        self.assertEqual(items[0]['refine_level'], 0)

        record, conversation = observe_barter(packet_id=0xb79, b79_variant='20260107')
        self.assertEqual(record['market_kind'], 'expanded_barter')
        self.assertIn('20260107', record['layout'])
        self.assertEqual(record['association'], 'after_close_list')
        code = BarterRenderer().render(record, item_ids_confirmed=True, conversation=conversation)
        self.assertIn('//-\tbarter\tGPA_B', code)
        self.assertIn('450206:-1:0 { 1000608:-1:100 }', code)
