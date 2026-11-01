import struct
import unittest

from events import PacketEvent
from reconstruction.barter import BarterStore, decode_expanded_barter
from reconstruction.barter_export import BarterRenderer, format_barter_items, script_refine
from reconstruction.dialogue import DialogueStore
from reconstruction.decoder import ObservationError
from tests.support.branches import NPC


def message(pid, body=b'', direction='recv', flow='game', timestamp=1.0):
    direction = {'recv': 'RECV', 'send': 'SEND'}.get(direction, direction)
    if pid == 0xb56:
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


def observe_barter(*, gap=1.0, items=None):
    """Close then 0x0B56 within the after-close window; returns record and conversation."""
    dialogues = DialogueStore()
    store = BarterStore(dialogues=dialogues)
    now = 1.0
    entries = items or [(450206, 4, -1, 0, [(1000608, 0, 100, 3)])]

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
