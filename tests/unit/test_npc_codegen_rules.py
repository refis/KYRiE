"""Regression coverage for NPC codegen rules (actor_id, menu/switch, warp, indent)."""
import struct
import unittest

from reconstruction.auriga import AurigaRenderer
from reconstruction.dialogue import DialogueStore
from reconstruction.entity_metadata import render_npc_initialization
from reconstruction.npc_bundle import build_npc_bundle
from reconstruction.shop_export import shop_name_for
from tests.support.branches import NPC, conversation
from tests.support.dialogue import packet


class NpcCodegenRulesTests(unittest.TestCase):
    def test_header_embeds_actor_id_and_oninit_label_is_flush(self):
        item = conversation()
        item.npc = dict(NPC, waitingrooms=[dict(title='最新情報！', limit=5)])
        code = AurigaRenderer().render_npc_file(item)
        self.assertIn('\tscript\t案内人\t45,{/* 42 */', code)
        self.assertIn('\nOnInit:\n', code)
        self.assertNotIn('\n    OnInit:', code)
        self.assertIn('waitingroom "最新情報！",0;', code)
        tabbed = AurigaRenderer(indent='\t').render_npc_file(item)
        self.assertIn('\n\tmes "hello";', tabbed)
        self.assertIn('\nOnInit:\n\twaitingroom "最新情報！",0;\n\tend;\n}', tabbed)

    def test_menu_set_switch_uses_temp_var_quoted_options_and_case_end_rules(self):
        item = conversation()
        code = AurigaRenderer().render(item)
        self.assertIn("set '@menu,select(\"one\",\"two\",\"three\");", code)
        self.assertIn("switch ('@menu) {", code)
        self.assertIn('case 1:\n        mes "one result";\n        close;\n        end;', code)
        self.assertIn('case 2:\n        // 未観測の分岐\n        end;', code)
        self.assertNotIn('break;', code)
        self.assertNotIn('menu "', code)
        self.assertNotIn(',-;', code)

    def test_same_name_placements_remain_active_with_warning(self):
        first = dict(NPC, kind='NPC', actor_id=42, capture_session=0, group_id=0, title=' ')
        second = dict(first, x=first['x'] + 1, actor_id=43)
        report = build_npc_bundle([first, second], [])
        self.assertEqual(report['review_only_count'], 0)
        self.assertEqual(report['auriga'].count('\tscript\t案内人\t'), 2)
        self.assertEqual(report['auriga'].count('同名・異配置のNPC'), 2)

    def test_callshop_name_is_map_scoped_and_input_vars_renamed(self):
        self.assertEqual(shop_name_for(dict(NPC), [dict(client_item_id=501, price=100)]), 'test.gat#callshop')
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0x142, struct.pack('<I', 42)))
        store.apply(packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'))
        store.apply(packet(0x1d4, struct.pack('<I', 42)))
        store.apply(packet(0x1d5, struct.pack('<I', 42) + b'abc\0', 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        item.npc = dict(NPC)
        code = AurigaRenderer().render(item)
        self.assertIn("input '@num;", code)
        self.assertIn("input '@str$;", code)
        self.assertNotIn('gpa_', code)

    def test_menu_choice_map_change_emits_executable_warp(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb7, struct.pack('<I', 42) + b'go:stay:\0'))
        store.apply(packet(0xb8, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0x91, b'dest.gat'.ljust(16, b'\0') + struct.pack('<HH', 5, 6)))
        item = store.sessions[0]
        item.npc = dict(NPC)
        self.assertEqual(item.status, 'map_changed')
        self.assertTrue(item.termination.get('after_menu_warp'))
        code = AurigaRenderer().render(item)
        self.assertIn('warp "dest.gat",5,6;', code)
        self.assertNotIn('マップ移動を観測', code)

    def test_waitingroom_force_zero_even_when_observed_limit_differs(self):
        text = render_npc_initialization([dict(NPC, waitingrooms=[dict(title='Queue', limit=12)])])
        self.assertIn('waitingroom "Queue",0;', text)
        self.assertNotIn(',12;', text)


if __name__ == '__main__':
    unittest.main()
