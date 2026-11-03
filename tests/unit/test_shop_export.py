from copy import deepcopy
import struct
import unittest

from events import PacketEvent
from reconstruction.dialogue import DialogueStore
from reconstruction.shops import ShopStore
from reconstruction.client_names import empty_client_names, load_client_names
from reconstruction.shop_export import ShopRenderer, format_shop_item_names
from tests.support.branches import NPC


def observe_shop(with_dialogue, close_first=False, gap=0, acknowledge=False, followup=False,
                 selector=True):
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
    if selector:
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
        for options, keyword in ((2, 'script(HIDDEN)'), (4, 'script(CLOAKED)')):
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
        self.assertIn('-\tshop\ttest.gat#callshop', code)
        self.assertIn('\tscript\t案内人\t45,{/*', code)
        self.assertIn('mes "before shop";', code)
        self.assertIn("switch ('@menu)", code)
        self.assertIn('close2;\n            callshop "test.gat#callshop', code)
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

    def test_after_close_list_without_selector_is_callshop_within_two_seconds(self):
        from reconstruction.npc_bundle import build_npc_bundle
        record, conversation = observe_shop(True, close_first=True, acknowledge=True, selector=False)
        self.assertEqual(record['association'], 'after_close_list')
        self.assertEqual(record['conversation_link_basis'], 'same_flow_after_close')
        self.assertEqual(conversation.status, 'shop_opened')
        self.assertTrue(conversation.termination.get('after_close_list'))
        self.assertEqual(conversation.termination.get('packet_id'), 0xc6)
        before = deepcopy((record, conversation))
        code = ShopRenderer().render(record, 'callshop', item_ids_confirmed=True, conversation=conversation)
        self.assertIn('-\tshop\ttest.gat#callshop', code)
        self.assertIn('close2;', code)
        self.assertIn('callshop "test.gat#callshop', code)
        self.assertLess(code.index('-\tshop\t'), code.index('\tscript\t'))
        with self.assertRaises(ValueError):
            ShopRenderer().render(record, 'shop', item_ids_confirmed=True, conversation=conversation)
        report = build_npc_bundle([], [conversation], shops=[record])
        self.assertIn('callshop "test.gat#callshop', report['auriga'])
        self.assertLess(report['auriga'].index('-\tshop\t'), report['auriga'].index('\tscript\t'))
        self.assertEqual((record, conversation), before)
        expired, closed = observe_shop(True, close_first=True, gap=3, acknowledge=True, selector=False)
        self.assertEqual(expired['association'], 'unresolved')
        self.assertIsNone(expired['conversation_id'])
        self.assertEqual(closed.status, 'closed')

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

    def test_shop_candidate_annotates_identified_names_without_rewriting_ids(self):
        catalog = load_client_names()
        empty = empty_client_names()
        direct, opened = observe_shop(False)
        before = deepcopy(direct)
        named = ShopRenderer(client_names=catalog).render(
            direct, 'shop', item_ids_confirmed=True, conversation=opened)
        self.assertIn('501:100', named)
        self.assertIn('// 品名（資料）: 501=赤ポーション', named)
        self.assertLess(named.index('品名（資料）'), named.index('501:100'))
        missing = ShopRenderer(client_names=empty).render(
            direct, 'shop', item_ids_confirmed=True, conversation=opened)
        self.assertIn('501:100', missing)
        self.assertIn('// 品名（資料）: 501=未登録', missing)
        self.assertEqual(format_shop_item_names(catalog, direct['items']), '501=赤ポーション')
        self.assertEqual(direct, before)
        record, conversation = observe_shop(True)
        callshop = ShopRenderer(client_names=catalog).render(
            record, 'callshop', item_ids_confirmed=True, conversation=conversation)
        self.assertIn('// 品名（資料）: 501=赤ポーション', callshop)
        self.assertIn('501:100', callshop)
        self.assertRegex(callshop, r'-\tshop\ttest\.gat#callshop\t-1,501:100')

    def test_world_backed_hidden_shop_keeps_actor_id_without_manual_npc_inject(self):
        """CI hang since Actions #135: generate raised ActorID missing → QMessageBox blocked offscreen."""
        import struct
        from dataclasses import replace
        from reconstruction.world import WorldStore
        from reconstruction.shop_export import ShopRenderer
        from tests.unit.test_npc_initial_state import actor
        from tests.unit.test_actor_identity import connection
        from tests.support.world import packet, map_packet
        from tests.support.display import variable

        endpoint = connection()
        world = WorldStore()
        dialogues = DialogueStore(world=world)
        shops = ShopStore(world=world, dialogues=dialogues)
        events = (
            map_packet(connection=endpoint),
            actor(2, endpoint),
            packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 0, 0), connection=endpoint),
            packet(0x90, struct.pack('<IB', 42, 1), connection=endpoint, direction='SEND'),
            packet(0xc4, struct.pack('<I', 42), connection=endpoint),
            packet(0xc5, struct.pack('<IB', 42, 0), connection=endpoint, direction='SEND'),
            replace(variable(0xc6, struct.pack('<IIBI', 100, 76, 3, 501), endpoint), timestamp=1),
        )
        for index, event in enumerate(events):
            world.apply(event)
            dialogues.apply(event, packet_index=index)
            shops.apply(event, packet_index=index)
        record = shops.records[0]
        conversation = dialogues.sessions[0]
        self.assertEqual(record['actor_id'], 42)
        self.assertEqual(record['npc'].get('actor_id'), 42)
        self.assertEqual(record['npc'].get('initial_options'), 2)
        before = deepcopy((record, conversation))
        code = ShopRenderer().render(record, 'shop', item_ids_confirmed=True, conversation=conversation)
        self.assertTrue(all(not line or line.startswith('//') for line in code.splitlines()))
        self.assertIn('501:100', code)
        self.assertIn('\tshop\t案内人\t45,501:100', code)
        self.assertEqual((record, conversation), before)

    def test_callshop_and_npc_file_accept_null_npc_actor_id_via_conversation(self):
        from reconstruction.auriga import AurigaRenderer
        record, conversation = observe_shop(True)
        conversation.npc = dict(conversation.npc, actor_id=None)
        record['npc'] = dict(record['npc'], actor_id=None)
        self.assertIsNone(conversation.npc['actor_id'])
        self.assertEqual(conversation.actor_id, 42)
        before = deepcopy((record, conversation))
        callshop = ShopRenderer().render(record, 'callshop', item_ids_confirmed=True, conversation=conversation)
        self.assertIn('callshop "test.gat#callshop"', callshop)
        self.assertIn('{/* 42 */', callshop)
        file_code = AurigaRenderer().render_npc_file(conversation)
        self.assertIn('{/* 42 */', file_code)
        self.assertEqual((record, conversation), before)
