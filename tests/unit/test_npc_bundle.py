import struct
import unittest
from copy import deepcopy

from reconstruction.auriga import AurigaRenderer
from reconstruction.dialogue import DialogueStore
from reconstruction.npc_bundle import build_npc_bundle
from tests.support.branches import NPC, conversation
from tests.support.dialogue import packet


def entity(**changes):
    return dict(NPC, kind='NPC', actor_id=42, capture_session=0, group_id=7, title='案内',
                metadata_evidence={'group_id': {'packet_id': 0xadf}, 'title': {'packet_id': 0xadf}}, **changes)


class NpcBundleTests(unittest.TestCase):
    def test_bundle_includes_direct_shop_dialogue_callshop_and_placement_only_with_spacing(self):
        from tests.unit.test_shop_export import observe_shop
        direct, direct_dialogue = observe_shop(False)
        direct['npc']['name'] = 'Direct'
        direct_dialogue.npc['name'] = 'Direct'
        direct_dialogue.id = 10
        direct['conversation_id'] = 10
        linked, dialogue = observe_shop(True)
        decoration = dict(entity(), name='Decoration', actor_id=99, group_id=0, title='  ')
        report = build_npc_bundle([decoration], [direct_dialogue, dialogue], merge=True, shops=[direct, linked])
        text = report['auriga']
        self.assertEqual(len(report['entries']), 3)
        self.assertFalse(report['excluded'])
        self.assertIn('\tshop\tDirect\t45,501:100', text)
        self.assertNotIn('\tscript\tDirect', text)
        self.assertIn('callshop "test.gat#callshop', text)
        self.assertIn('-\tshop\ttest.gat#callshop', text)
        self.assertIn('\tscript\tDecoration', text)
        self.assertNotIn('OnInit:', text)
        self.assertIn('未照合', text)
        self.assertIn('\n\n', text)
        conflict = deepcopy(direct)
        conflict['items'][0]['price'] = 200
        reviewed = build_npc_bundle([], [direct_dialogue], shops=[direct, conflict])
        self.assertEqual(reviewed['review_only_count'], 1)
        self.assertTrue(all(not line.strip() or line.startswith('//') for line in reviewed['auriga'].splitlines()))

    def test_bundle_places_commented_barter_before_npc_and_callbarter_in_body(self):
        from tests.unit.test_barter import observe_barter
        record, conversation = observe_barter()
        report = build_npc_bundle([], [conversation], barters=[record])
        self.assertFalse(report['excluded'])
        self.assertEqual(len(report['entries']), 1)
        self.assertTrue(report['entries'][0]['review_only'])
        text = report['auriga']
        self.assertIn('// barterの編集用候補', text)
        self.assertIn('//-\tbarter\ttest.gat#callbarter', text)
        self.assertIn('// callbarter "test.gat#callbarter', text)
        self.assertLess(text.index('// barterの編集用候補'), text.index('//-\tbarter\t'))
        self.assertLess(text.index('//-\tbarter\t'), text.index('\tscript\t'))
        self.assertLess(text.index('close2;'), text.index('// callbarter "'))

    def test_bundle_callshop_keeps_item_name_review_like_individual(self):
        from reconstruction.client_names import empty_client_names
        from reconstruction.shop_export import ShopRenderer
        from tests.unit.test_shop_export import observe_shop
        linked, dialogue = observe_shop(True)
        catalog = empty_client_names()
        catalog['tables']['item_identified']['501'] = '赤ポーション'
        individual = ShopRenderer(client_names=catalog).render(
            linked, 'callshop', conversation=dialogue, review_unconfirmed=True)
        report = build_npc_bundle([], [dialogue], shops=[linked], client_names=catalog)
        text = report['auriga']
        self.assertIn('// 品名（資料）: 501=赤ポーション', individual)
        self.assertIn('// 品名（資料）: 501=赤ポーション', text)
        self.assertIn('// shop/callshopの編集用候補', text)
        self.assertLess(text.index('品名（資料）'), text.index('-\tshop\ttest.gat#callshop'))
        self.assertLess(text.index('-\tshop\ttest.gat#callshop'), text.index('\tscript\t'))

    def test_bundle_shop_dialogues_follow_merge_checkbox_without_mutating_inputs(self):
        from tests.unit.test_shop_export import observe_shop
        record, first = observe_shop(True)
        second, second_record = deepcopy(first), deepcopy(record)
        second.id, second_record['conversation_id'] = 2, 2
        next(step for step in second.steps if step['kind'] == 'choice')['fields']['value'] = 2
        before = deepcopy((record, first, second, second_record))
        off = build_npc_bundle([], [first, second], shops=[record, second_record])
        on = build_npc_bundle([], [first, second], shops=[record, second_record], merge=True)
        self.assertEqual(off['auriga'].count('callshop "test.gat#callshop'), 2)
        self.assertEqual(on['auriga'].count('callshop "test.gat#callshop'), 1)
        self.assertEqual(on['auriga'].count('-\tshop\ttest.gat#callshop'), 1)
        self.assertEqual((record, first, second, second_record), before)

    def test_distinct_shop_products_stay_bound_to_each_menu_response(self):
        from reconstruction.shop_export import shop_name_for
        from tests.unit.test_shop_export import observe_shop
        record, first = observe_shop(True)
        second, other = deepcopy(first), deepcopy(record)
        second.id, other['conversation_id'] = 2, 2
        next(step for step in second.steps if step['kind'] == 'choice')['fields']['value'] = 2
        other['items'][0].update(client_item_id=502, price=200)
        name = shop_name_for(first.npc, record['items'])
        self.assertEqual(name, 'test.gat#callshop')
        self.assertEqual(shop_name_for(second.npc, other['items']), name)
        before = deepcopy((first, second, record, other))
        report = build_npc_bundle([], [first, second], shops=[record, other], merge=True)
        code = report['auriga']
        self.assertFalse(report['excluded'])
        # Same map#callshop with different item lists is review-only conflict.
        self.assertTrue(report['entries'][0]['shop_conflict'])
        self.assertIn('501:100', code)
        self.assertIn('502:200', code)
        self.assertIn('callshop "' + name + '";', code)
        self.assertEqual((first, second, record, other), before)
        next(step for step in second.steps if step['kind'] == 'choice')['fields']['value'] = 1
        conflicting = build_npc_bundle([], [first, second], shops=[record, other], merge=True)
        self.assertTrue(conflicting['entries'][0]['shop_conflict'])
        self.assertEqual(conflicting['review_only_count'], 1)

    def test_invalid_initial_state_excludes_only_affected_placement_with_evidence(self):
        healthy = dict(entity(), name='Healthy', actor_id=99, initial_options=0)
        for invalid in (-1, True, 'hidden', 0x100000000):
            for merge in (False, True):
                with self.subTest(invalid=invalid, merge=merge):
                    broken = dict(entity(), name='Broken', initial_options=invalid)
                    before = deepcopy((healthy, broken))
                    report = build_npc_bundle([broken, healthy], [], merge=merge)
                    self.assertEqual(len(report['entries']), 1)
                    self.assertEqual(report['entries'][0]['npc']['name'], 'Healthy')
                    self.assertIn('\tscript\tHealthy', report['auriga'])
                    self.assertNotIn('\tscript\tBroken', report['auriga'])
                    self.assertEqual(len(report['excluded']), 1)
                    excluded = report['excluded'][0]
                    self.assertEqual(excluded['kind'], 'npc_initial_state')
                    self.assertTrue(excluded['reason'])
                    self.assertEqual(excluded['entities'], [broken])
                    self.assertEqual(excluded['observations'], [broken])
                    self.assertEqual((healthy, broken), before)

    def test_bundle_npc_summary_keeps_initial_state_used_by_placement_code(self):
        unknown = entity()
        unknown.update(initial_options=None, initial_state_evidence={}, options=0)
        item = conversation()
        item.npc = deepcopy(unknown)
        evidence = {'packet_id': 0x9ff, 'packet_index': 12, 'capture_session': 0}
        item.npc.update(initial_options=2, initial_state_evidence=evidence)
        before = deepcopy((unknown, item))
        for merge in (False, True):
            with self.subTest(merge=merge):
                report = build_npc_bundle([unknown], [item], merge=merge)
                entry = report['entries'][0]
                self.assertIn('\tscript(HIDDEN)\t', entry['auriga'])
                self.assertEqual(entry['npc']['initial_options'], 2)
                self.assertEqual(entry['npc']['initial_state_evidence'], evidence)
                self.assertIsNone(entry['entities'][0]['initial_options'])
                self.assertEqual(entry['npc']['options'], 0)
                self.assertEqual(report['review_only_count'], 0)
                entry['npc']['initial_state_evidence']['packet_index'] = 999
        self.assertEqual((unknown, item), before)

    def test_direct_shop_visibility_review_count_matches_commented_output(self):
        from tests.unit.test_shop_export import observe_shop
        for options in (0, 2, 4, 6):
            for merge in (False, True):
                with self.subTest(options=options, merge=merge):
                    record, item = observe_shop(False)
                    record['npc']['initial_options'] = options
                    item.npc['initial_options'] = options
                    before = deepcopy((record, item))
                    report = build_npc_bundle([], [item], shops=[record], merge=merge)
                    entry = report['entries'][0]
                    self.assertFalse(report['excluded'])
                    self.assertEqual(entry['review_only'], options != 0)
                    self.assertEqual(report['review_only_count'], int(options != 0))
                    self.assertIn(entry['auriga'].rstrip(), report['auriga'])
                    if options:
                        self.assertTrue(all(not line.strip() or line.startswith('//')
                                            for line in entry['auriga'].splitlines()))
                        from reconstruction.shop_export import ShopRenderer
                        expected = ShopRenderer().render(record, 'shop', conversation=item, review_unconfirmed=True)
                        self.assertEqual(entry['auriga'].strip(), expected.strip())
                    self.assertEqual((record, item), before)
        # Supported script visibility modifiers do not require commenting a callshop NPC.
        for options in (2, 4):
            record, item = observe_shop(True)
            record['npc']['initial_options'] = item.npc['initial_options'] = options
            report = build_npc_bundle([], [item], shops=[record], merge=True)
            self.assertEqual(report['review_only_count'], 0)
            self.assertIn('callshop "', report['auriga'])

    def test_ambiguous_shop_binding_is_review_only_in_json_and_text(self):
        import json
        from tests.unit.test_shop_export import observe_shop
        record, item = observe_shop(True)
        other = deepcopy(record)
        other['items'][0]['price'] = 200
        before = deepcopy((record, other, item))
        for merge in (False, True):
            report = build_npc_bundle([], [item], shops=[record, other], merge=merge)
            self.assertEqual(report['review_only_count'], 1)
            exported = json.loads(json.dumps(report))
            entry = exported['entries'][0]
            self.assertTrue(entry['shop_conflict'])
            self.assertTrue(entry['review_only'])
            self.assertEqual(len(entry['shops']), 2)
            self.assertIn('501:100', entry['auriga'])
            self.assertIn('501:200', entry['auriga'])
            self.assertIn(entry['auriga'].rstrip(), exported['auriga'])
            self.assertTrue(all(not line.strip() or line.startswith('//')
                                for line in entry['auriga'].splitlines()))
        self.assertEqual((record, other, item), before)
        invalid = deepcopy(record)
        invalid['association'] = 'unresolved'
        report = build_npc_bundle([], [item], shops=[invalid])
        self.assertEqual(report['excluded'][0]['kind'], 'shop')
        self.assertEqual(report['excluded'][0]['record'], invalid)
        self.assertNotIn('callshop "', report['entries'][0]['auriga'])

    def test_initialization_only_has_entry_end_but_closed_dialogue_does_not_gain_one(self):
        npc = entity()
        store = DialogueStore()
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                      packet(0xb6, struct.pack('<I', 42))):
            store.apply(event)
        item = store.sessions[0]
        item.npc = dict(npc)
        renderer = AurigaRenderer()
        self.assertTrue(renderer.render_npc_metadata_file(npc).split('OnInit:')[0].rstrip().endswith('end;'))
        prefix = renderer.render(item).split('OnInit:')[0].rstrip()
        self.assertTrue(prefix.endswith('close;'))
        self.assertNotIn('end;', prefix)
        text = build_npc_bundle([npc], [], merge=True)['auriga']
        self.assertTrue(text.split('OnInit:')[0].rstrip().endswith('end;'))
        unknown = build_npc_bundle([dict(npc, metadata_evidence={})], [])
        self.assertEqual(len(unknown['entries']), 1)
        self.assertNotIn('OnInit:', unknown['auriga'])
        self.assertNotIn('end;', unknown['auriga'])
        self.assertIn('45,{/* 42 */}', unknown['auriga'])

    def test_bundle_appends_onquestinfo_after_oninit_from_linked_showevent(self):
        from reconstruction.quests import ADD_LENGTHS
        from reconstruction.world import WorldStore
        from tests.support.world import map_packet, actor_packet
        world = WorldStore()
        store = DialogueStore(world=world)
        name = 'レイジー#ep20_end01'
        events = [
            map_packet(), actor_packet(name=name),
            packet(0x90, struct.pack('<IB', 42, 1), 'SEND', connection='flow-a', flow=''),
            packet(0xb4, struct.pack('<I', 42) + b'hello\0', connection='flow-a', flow=''),
            packet(0xb0c, struct.pack('<IBIIH', 3593, 1, 0, 999, 2) + bytes(ADD_LENGTHS[0xb0c] - 17),
                   connection='flow-a', flow=''),
            packet(0x446, struct.pack('<IHHHH', 42, 368, 222, 0, 1), connection='flow-a', flow=''),
            packet(0xb6, struct.pack('<I', 42), connection='flow-a', flow=''),
        ]
        for event in events:
            world.apply(event)
            store.apply(event)
        item = store.sessions[0]
        npc = entity(name=name, map_name=item.npc.get('map_name') or 'prontera.gat',
                     x=item.npc.get('x', 150), y=item.npc.get('y', 200),
                     direction=item.npc.get('direction', 3))
        item.npc = dict(npc)
        self.assertEqual(len(item.quest_info_links), 1)
        before = deepcopy((npc, item))
        text = build_npc_bundle([npc], [item], merge=True)['auriga']
        self.assertIn('OnInit:', text)
        self.assertIn('OnQuestInfo:', text)
        self.assertLess(text.index('OnInit:'), text.index('OnQuestInfo:'))
        self.assertIn('showevent 0, 1, "レイジー#ep20_end01";', text)
        self.assertIn('// 3593: 368, 222', text)
        self.assertNotIn('\n    OnQuestInfo:', text)
        self.assertEqual((npc, item), before)

    def test_bulk_merge_toggle_keeps_all_paths_one_declaration_and_one_initialization(self):
        npc = entity()
        first, second = conversation(), conversation(2, answer='other', identifier=2)
        for item in (first, second):
            item.npc.update(npc)
        before = deepcopy((npc, first, second))
        off = build_npc_bundle([npc], [first, second], merge=False)
        on = build_npc_bundle([npc], [first, second], merge=True)
        self.assertEqual(off['auriga'].count("switch ('@menu)"), 2)
        self.assertEqual(on['auriga'].count("switch ('@menu)"), 1)
        for report in (off, on):
            self.assertEqual(len(report['entries']), 1)
            self.assertEqual(report['auriga'].count('OnInit:'), 1)
            self.assertEqual(report['auriga'].count('\tscript\t'), 1)
            self.assertIn('mes "other";', report['auriga'])
            self.assertFalse(report['excluded'])
        self.assertEqual((npc, first, second), before)
        partial_store = DialogueStore()
        partial_store.apply(packet(0xb4, struct.pack('<I', 42) + b'partial\0'))
        partial_store.apply(packet(0xb6, struct.pack('<I', 42)))
        partial = partial_store.sessions[0]
        partial.id, partial.npc = 3, dict(npc)
        preserved = build_npc_bundle([npc], [first, second, partial], merge=True)
        self.assertIn('mes "partial";', preserved['auriga'])
        self.assertIn('会話開始は未観測', preserved['auriga'])
        self.assertEqual(preserved['entries'][0]['merge_exclusions'][0]['reason'], 'open_unobserved')

    def test_missing_data_and_duplicate_names_are_preserved_without_renaming(self):
        npc = entity()
        other = dict(npc, x=npc['x'] + 1, actor_id=43)
        invalid = dict(npc, map_name=None, actor_id=44)
        report = build_npc_bundle([npc, other, invalid], [])
        self.assertEqual(len(report['entries']), 2)
        self.assertEqual(report['review_only_count'], 0)
        self.assertEqual(report['excluded'][0]['npc']['actor_id'], 44)
        for entry in report['entries']:
            self.assertIn(entry['auriga'].rstrip(), report['auriga'])
            self.assertIn('同名・異配置のNPC', entry['auriga'])
            self.assertTrue(any(line.startswith('test.gat,') and '\tscript\t' in line
                                for line in entry['auriga'].splitlines()))
        self.assertIn('\tscript\t', report['auriga'])

    def test_invalid_initial_class_is_isolated_from_other_placements(self):
        for initial in (None,-1,True,65536,'bad'):
            with self.subTest(initial=initial):
                bad=entity();bad['initial_display']={'class_id':initial}
                good=entity();good.update(name='Valid',actor_id=43)
                result=build_npc_bundle([bad,good],[])
                self.assertEqual(len(result['entries']),1)
                self.assertEqual(result['entries'][0]['npc']['name'],'Valid')
                self.assertEqual(len(result['excluded']),1)

    def test_bundle_order_follows_server_actor_even_when_names_have_reverse_order(self):
        entities=[]
        for name,ip,port,aid in [('Alpha','10.0.0.10',5121,1),('Beta','10.0.0.2',6121,1),
                                 ('Gamma','10.0.0.2',5121,10),('Zulu','10.0.0.2',5121,2)]:
            row=entity();row.update(name=name,server_endpoint=dict(ip=ip,port=port),actor_id=aid)
            entities.append(row)
        for merge in (False,True):
            report=build_npc_bundle(entities,[],merge=merge)
            self.assertEqual([e['npc']['name'] for e in report['entries']],['Zulu','Gamma','Beta','Alpha'])
            positions=[report['auriga'].index('\tscript\t'+name+'\t') for name in ('Zulu','Gamma','Beta','Alpha')]
            self.assertEqual(positions,sorted(positions))

    def test_callshop_name_uses_record_actor_id_when_conversation_npc_omits_it(self):
        """#114 leftover: bundle shop_name_for must not abort when npc lacks actor_id."""
        from tests.unit.test_shop_export import observe_shop
        record, conversation = observe_shop(True)
        conversation.npc = {key: value for key, value in conversation.npc.items() if key != 'actor_id'}
        record['npc'] = {key: value for key, value in record['npc'].items() if key != 'actor_id'}
        self.assertNotIn('actor_id', conversation.npc)
        self.assertEqual(record['actor_id'], 42)
        before = deepcopy((record, conversation))
        report = build_npc_bundle([], [conversation], shops=[record])
        self.assertFalse(report['excluded'])
        self.assertIn('callshop "test.gat#callshop"', report['auriga'])
        self.assertEqual((record, conversation), before)

    def test_bundle_sort_uses_npc_actor_id_when_reference_actor_id_is_null(self):
        """Explicit None on shop record must not sort as the 0x100000000 sentinel."""
        from tests.unit.test_shop_export import observe_shop
        high = dict(entity(), name='High', actor_id=100, capture_session=0,
                    server_endpoint=dict(ip='10.0.0.2', port=5121))
        record, _opened = observe_shop(False)
        record['npc'] = dict(record['npc'], name='LowShop', actor_id=2, kind='NPC',
                             capture_session=0, server_endpoint=dict(ip='10.0.0.2', port=5121),
                             group_id=7, title='案内',
                             metadata_evidence={'group_id': {'packet_id': 0xadf},
                                                'title': {'packet_id': 0xadf}})
        record['actor_id'] = None
        record['conversation_id'] = None
        record['conversation_link_basis'] = None
        before = deepcopy((high, record))
        report = build_npc_bundle([high], [], shops=[record])
        self.assertFalse(report['excluded'])
        names = [entry['npc']['name'] for entry in report['entries']]
        self.assertEqual(names, ['LowShop', 'High'])
        self.assertLess(report['auriga'].index('\tshop\tLowShop\t'),
                        report['auriga'].index('\tscript\tHigh\t'))
        self.assertEqual((high, record), before)
