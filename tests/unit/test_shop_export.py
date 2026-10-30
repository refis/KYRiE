from copy import deepcopy
import struct
import unittest

from events import PacketEvent
from reconstruction.dialogue import DialogueStore
from reconstruction.shops import ShopStore
from reconstruction.shop_export import ShopRenderer
from tests.support.branches import NPC


def observe_shop(with_dialogue, close_first=False, gap=0, acknowledge=False, followup=False):
    dialogues = DialogueStore()
    shops = ShopStore(dialogues=dialogues)
    now = 1
    def consume(pid, body, direction='RECV'):
        raw = struct.pack('<H', pid)
        if pid in (0xb4, 0xb7, 0xc6):
            raw += struct.pack('<H', len(body) + 4)
        event = PacketEvent(now, direction, pid, raw + body, 'NPCAP', 'half', 'game')
        index = dialogues.packet_ordinal
        shops.apply(event, packet_index=index)
        dialogues.apply(event, packet_index=index)
    consume(0x90, struct.pack('<IB', 42, 1), 'SEND')
    if with_dialogue:
        consume(0xb4, struct.pack('<I', 42) + b'before shop\0')
        consume(0xb7, struct.pack('<I', 42) + b'buy:leave:\0')
        consume(0xb8, struct.pack('<IB', 42, 1), 'SEND')
    if close_first:
        consume(0xb6, struct.pack('<I', 42))
        now += gap
        if acknowledge:
            consume(0x146, struct.pack('<I', 42), 'SEND')
        if followup:
            consume(0x19b, struct.pack('<II', 42, 123))
            if followup == 'reopen':
                consume(0xb4, struct.pack('<I', 42) + b'reopened dialogue\0')
    consume(0xc4, struct.pack('<I', 42))
    consume(0xc5, struct.pack('<IB', 42, 0), 'SEND')
    consume(0xc6, struct.pack('<IIBI', 100, 76, 0, 501))
    item = dialogues.sessions[0]
    item.npc = dict(NPC)
    record = shops.records[0]
    record['npc'] = dict(NPC)
    return record, item


class ShopExportTests(unittest.TestCase):
    def test_initial_hidden_or_cloaked_direct_shop_is_commented_and_callshop_keeps_script_state(self):
        renderer = ShopRenderer()
        for options, keyword in ((2, 'script(HIDDEN)'), (4, 'script2(CLOAKED)')):
            record, opened = observe_shop(False)
            record['npc'].update(initial_options=options, options=0)
            before = deepcopy(record)
            code = renderer.render(record, 'shop', item_ids_confirmed=True, conversation=opened)
            self.assertTrue(all(not line or line.startswith('//') for line in code.splitlines()))
            self.assertIn('501:100', code)
            self.assertEqual(record, before)
            linked, conversation = observe_shop(True)
            conversation.npc.update(initial_options=options, options=0)
            code = renderer.render(linked, 'callshop', item_ids_confirmed=True, conversation=conversation)
            self.assertIn('\t' + keyword + '\t', code)
            self.assertIn('callshop "', code)

    def test_direct_shop_and_dialogue_callshop_have_distinct_structures(self):
        renderer = ShopRenderer()
        direct, opened = observe_shop(False)
        code = renderer.render(direct, 'shop', item_ids_confirmed=True, conversation=opened)
        self.assertIn('test.gat,10,20,0\tshop\t案内人\t45,501:100', code)
        self.assertNotIn('501:76', code)
        self.assertNotIn('callshop "', code)
        record, conversation = observe_shop(True)
        before = deepcopy(conversation)
        code = renderer.render(record, 'callshop', item_ids_confirmed=True, conversation=conversation)
        self.assertIn('-\tshop\tGPA_S', code)
        self.assertIn('\tscript\t案内人\t45,{', code)
        self.assertIn('mes "before shop";', code)
        self.assertIn('switch (@menu)', code)
        self.assertIn('close2;\n            callshop "GPA_S', code)
        self.assertLess(code.index('callshop "'), code.index('end;'))
        self.assertEqual(conversation, before)
        record, closed = observe_shop(True, close_first=True)
        self.assertEqual(record['conversation_link_basis'], 'same_flow_after_close')
        code = renderer.render(record, 'callshop', item_ids_confirmed=True, conversation=closed)
        self.assertEqual(code.count('close2;'), 1)
        self.assertLess(code.index('callshop "'), code.index('end;'))
        expired, _ = observe_shop(True, close_first=True, gap=3)
        self.assertIsNone(expired['conversation_id'])

    def test_acknowledged_close_with_effect_before_shop_waits_only_once(self):
        from reconstruction.npc_bundle import build_npc_bundle
        record, conversation = observe_shop(True, close_first=True, acknowledge=True, followup=True)
        before = deepcopy((record, conversation))
        code = ShopRenderer().render(record, 'callshop', item_ids_confirmed=True, conversation=conversation)
        self.assertEqual(code.count('close2;'), 1)
        self.assertLess(code.index('close2;'), code.index('misceffect'))
        self.assertLess(code.index('misceffect'), code.index('callshop "'))
        for merge in (False, True):
            report = build_npc_bundle([], [conversation], shops=[record], merge=merge)
            self.assertFalse(report['excluded'])
            self.assertEqual(report['auriga'].count('close2;'), 1)
            self.assertIn('callshop "', report['auriga'])
        self.assertEqual((record, conversation), before)
        reopened_record, reopened = observe_shop(True, close_first=True, acknowledge=True, followup='reopen')
        code = ShopRenderer().render(reopened_record, 'callshop', item_ids_confirmed=True, conversation=reopened)
        self.assertEqual(code.count('close2;'), 2)
        self.assertLess(code.index('mes "reopened dialogue";'), code.rindex('close2;'))
        self.assertLess(code.rindex('close2;'), code.index('callshop "'))

    def test_confirmation_placement_and_observed_transition_are_required(self):
        renderer = ShopRenderer()
        record, conversation = observe_shop(True)
        with self.assertRaises(ValueError):
            renderer.render(record, 'callshop', conversation=conversation)
        with self.assertRaises(ValueError):
            renderer.render(record, 'shop', item_ids_confirmed=True, conversation=conversation)
        bad = deepcopy(conversation)
        bad.termination['packet_index'] += 1
        with self.assertRaises(ValueError):
            renderer.render(record, 'callshop', item_ids_confirmed=True, conversation=bad)
        pending = deepcopy(conversation)
        del pending.steps[2]['reply']
        with self.assertRaises(ValueError):
            renderer.render(record, 'callshop', item_ids_confirmed=True, conversation=pending)
        direct, opened = observe_shop(False)
        with self.assertRaises(ValueError):
            renderer.render(direct, 'callshop', item_ids_confirmed=True, conversation=opened)
        direct['npc']['map_name'] = None
        with self.assertRaises(ValueError):
            renderer.render(direct, 'shop', item_ids_confirmed=True, conversation=opened)
        code = renderer.render(direct, 'shop', item_ids_confirmed=True, conversation=opened, map_name='test.gat')
        self.assertIn('利用者入力', code)
        direct['items'].append(deepcopy(direct['items'][0]))
        with self.assertRaises(ValueError):
            renderer.render(direct, 'shop', item_ids_confirmed=True, conversation=opened, map_name='test.gat')
