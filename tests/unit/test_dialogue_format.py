import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from reconstruction.auriga import AurigaRenderer, DEFAULT_DIALOGUE_PROFILE, STYLE_FIELDS, PRESENTATION_FIELDS, FILE_FIELDS
from reconstruction.branches import build_merged
from reconstruction.dialogue import DialogueStore
from tests.support.branches import conversation, NPC
from tests.support.dialogue import packet


def simple(choice=1, options=('one', 'two'), value=None, text_input=False, opening='hello', answer='answer'):
    store = DialogueStore()
    def add(pid, data=b'', direction='RECV'):
        store.apply(packet(pid, data, direction))
    add(0x90, struct.pack('<IB', 42, 1), 'SEND')
    add(0xb4, struct.pack('<I', 42) + opening.encode('cp932') + b'\0')
    if options:
        add(0xb7, struct.pack('<I', 42) + (':'.join(options) + ':').encode('cp932') + b'\0')
        add(0xb8, struct.pack('<IB', 42, choice), 'SEND')
    if value is not None:
        add(0x1d4 if text_input else 0x142, struct.pack('<I', 42))
        if text_input:
            add(0x1d5, struct.pack('<I', 42) + str(value).encode('cp932') + b'\0', 'SEND')
        else:
            add(0x143, struct.pack('<Ii', 42, value), 'SEND')
    add(0xb4, struct.pack('<I', 42) + answer.encode('cp932') + b'\0')
    add(0xb6, struct.pack('<I', 42))
    item = store.sessions[0]
    item.npc = dict(NPC)
    return item


def merged(*items):
    report = build_merged((str(i), item) for i, item in enumerate(items))
    return report, AurigaRenderer().render_merged(report['groups'][0])


def returning_menu(barrier=None, answers=('help', 'help'), options=('again', 'exit'), presentation=None):
    store = DialogueStore()
    def add(pid, body=b'', direction='RECV'):
        store.apply(packet(pid, body, direction))
    actor = struct.pack('<I', 42)
    add(0x90, actor + b'\1', 'SEND')
    add(0xb4, actor + b'intro\0')
    for index, answer in enumerate((*answers, 'bye')):
        current = options if barrier != 'different' or index == 0 else ('changed', 'exit')
        add(0xb7, actor + (':'.join(current) + ':').encode('cp932') + b'\0')
        add(0xb8, actor + bytes([1 if index < len(answers) else 2]), 'SEND')
        add(0xb4, actor + answer.encode('cp932') + b'\0')
        if index < len(answers):
            if presentation is not None:
                store.apply(presentation)
            if barrier == 'input':
                add(0x142, actor)
                add(0x143, actor + struct.pack('<i', index), 'SEND')
            else:
                add(0xb5, actor)
                add(0xb9, actor, 'SEND')
            if barrier == 'cutin':
                add(0x1b3, b'image.bmp'.ljust(64, b'\0') + bytes([index % 2]))
    add(0xb6, actor)
    result = store.sessions[0]
    result.npc = dict(NPC)
    return result


def converging_menu(outer_choice, inner_choices, *, different=False, input_barrier=False, presentation=None):
    store = DialogueStore()
    actor = struct.pack('<I', 42)
    def add(pid, body=b'', direction='RECV'):
        store.apply(packet(pid, body, direction))
    add(0x90, actor + b'\1', 'SEND')
    add(0xb4, actor + b'intro\0')
    add(0xb7, actor + b'outer one:outer two:\0')
    add(0xb8, actor + bytes([outer_choice]), 'SEND')
    answer = f'different {outer_choice}' if different else 'same response'
    add(0xb4, actor + answer.encode('cp932') + b'\0')
    if presentation is not None:
        store.apply(presentation)
    add(0xb5, actor)
    add(0xb9, actor, 'SEND')
    if input_barrier:
        add(0x142, actor)
        add(0x143, actor + struct.pack('<i', outer_choice), 'SEND')
    for index, choice in enumerate(inner_choices):
        add(0xb7, actor + b'explain:sign:leave:\0')
        add(0xb8, actor + bytes([choice]), 'SEND')
        add(0xb4, actor + f'result {choice}'.encode() + b'\0')
        if index + 1 < len(inner_choices):
            add(0xb5, actor)
            add(0xb9, actor, 'SEND')
    add(0xb6, actor)
    result = store.sessions[0]
    result.npc = dict(NPC)
    return result


class DialogueFormatTests(unittest.TestCase):
    def test_new_presentations_do_not_block_return_loops_or_identical_menu_continuations(self):
        from tests.support.dialogue import overhead_event, viewpoint_event
        events = [(overhead_event(text='look'), overhead_event(text='different'), 'showmessage "look";'),
                  (viewpoint_event(), viewpoint_event(x=101), 'viewpoint 1,100,200'),
                  (packet(0x1b0, struct.pack('<IBI', 42, 1, 1005)),
                   packet(0x1b0, struct.pack('<IBI', 42, 1, 1006)), 'setnpcdisplay "案内人",1005;'),
                  (packet(0x9d1, struct.pack('<III', 42, 0xabcdef, 3)),
                   packet(0x9d1, struct.pack('<III', 42, 0xabcdef, 4)), '秒数=3')]
        events.extend([
            (packet(0xba2, struct.pack('<II',180,280)), packet(0xba2, struct.pack('<II',200,320)), 'messize 180,280;'),
            (packet(0xba3, struct.pack('<II',10,20)), packet(0xba3, struct.pack('<II',30,40)), 'mespos 10,20;'),
            (packet(0xbb5, struct.pack('<II',10,20)), packet(0xbb5, struct.pack('<II',30,40)), 'mespos 10,20;'),
            (packet(0xba1, b'\x01'), packet(0xba1, b'\x02'), 'mesalign 1;')])
        for event, variant, marker in events:
            with self.subTest(pid=event.packet_id):
                item = returning_menu(presentation=event)
                original = copy.deepcopy(item)
                report, code = merged(item)
                nodes = copy.deepcopy(report['groups'][0]['nodes'])
                for rendered in (code, AurigaRenderer().render(item)):
                    self.assertEqual(rendered.count('while (1)'), 1)
                    self.assertEqual(rendered.count('menu("again","exit")'), 1)
                    self.assertIn('continue;', rendered)
                    self.assertIn(marker, rendered)
                self.assertEqual(item, original)
                self.assertEqual(report['groups'][0]['nodes'], nodes)
                first = converging_menu(1, (3,), presentation=event)
                second = converging_menu(2, (1, 1, 2), presentation=event)
                _, joined = merged(first, second)
                self.assertEqual(joined.count('menu "outer one","outer two";'), 1)
                self.assertEqual(joined.count('mes "same response";'), 1)
                self.assertEqual(joined.count('menu("explain","sign","leave")'), 1)
                self.assertNotIn('未観測の分岐', joined)
                self.assertIn(marker, joined)
                _, separate = merged(first, converging_menu(2, (1, 1, 2), presentation=variant))
                self.assertGreater(separate.count('mes "same response";'), 1)

    def test_identical_responses_join_next_menu_coverage_before_folding_its_loop(self):
        first = converging_menu(1, (3,))
        second = converging_menu(2, (1, 1, 2))
        before = copy.deepcopy((first, second))
        report, code = merged(first, second)
        self.assertEqual(code.count('menu "outer one","outer two";'), 1)
        self.assertEqual(code.count('mes "same response";'), 1)
        self.assertEqual(code.count('menu("explain","sign","leave")'), 1)
        self.assertEqual(code.count("switch ('@menu)"), 1)
        self.assertEqual(code.count('while (1)'), 1)
        self.assertIn('continue;', code)
        self.assertNotIn('未観測の分岐', code)
        for choice in (1, 2, 3):
            self.assertEqual(code.count(f'case {choice}:'), 1)
            self.assertEqual(code.count(f'mes "result {choice}";'), 1)
        self.assertEqual((first, second), before)
        self.assertEqual(AurigaRenderer().render_merged(report['groups'][0]), code)
        for options in (dict(different=True), dict(input_barrier=True)):
            with self.subTest(options=options):
                _, separate = merged(converging_menu(1, (3,), **options),
                                     converging_menu(2, (1, 1, 2), **options))
                self.assertGreater(separate.count("switch ('@menu)"), 1)
                self.assertEqual(separate.count('menu("explain","sign","leave")'), 2)
                self.assertIn('未観測の分岐', separate)
        _, partial = merged(second)
        self.assertIn('未観測の分岐', partial)
        self.assertEqual(partial.count("switch ('@menu)"), 2)
        renderer = AurigaRenderer()
        nodes = report['groups'][0]['nodes']
        preserved = renderer._render_nodes(nodes, [], allow_identical_menu=False)
        self.assertEqual(preserved.count('menu("explain","sign","leave")'), 2)

    def test_repeated_menu_returns_use_one_while_and_keep_variants_unknowns_and_evidence(self):
        renderer = AurigaRenderer()
        for answers in (('help', 'help'), ('first variant', 'second variant')):
            with self.subTest(answers=answers):
                item = returning_menu(answers=answers, options=('again', 'exit', 'unseen'))
                before = copy.deepcopy(item)
                report = build_merged([('a', item)])
                group = report['groups'][0]
                nodes_before = copy.deepcopy(group['nodes'])
                for code in (renderer.render(item), renderer.render_merged(group)):
                    self.assertEqual(code.count('while (1) {'), 1)
                    self.assertEqual(code.count('menu("again","exit","unseen")'), 1)
                    self.assertEqual(code.count("switch ('@menu)"), 1)
                    self.assertIn('continue;', code)
                    self.assertIn('case 3:', code)
                    self.assertIn('未観測の分岐', code)
                    self.assertIn('mes "bye";', code)
                    self.assertEqual(code.count('{'), code.count('}'))
                    for answer in set(answers):
                        self.assertEqual(code.count(f'mes "{answer}";'), 1)
                    if len(set(answers)) > 1:
                        self.assertIn('別観測 2', code)
                self.assertEqual(item, before)
                self.assertEqual(group['nodes'], nodes_before)
        with self.assertRaises(ValueError):
            renderer.render_merged(group, max_pending_actions=2)
        long_code = renderer.render(returning_menu(answers=('help',) * 40))
        self.assertEqual(long_code.count('while (1)'), 1)
        self.assertEqual(long_code.count("switch ('@menu)"), 1)
        self.assertEqual(long_code.count('mes "help";'), 1)
        single = returning_menu(answers=('help',))
        for step in single.steps:
            if step['kind'] == 'menu':
                step['fields']['options'] = ['again']
            elif step['kind'] == 'choice':
                step['fields']['value'] = 1
        single_code = renderer.render(single)
        self.assertEqual(single_code.count('menu "again";'), 1)
        self.assertIn('while (1)', single_code)
        self.assertNotIn('switch', single_code)

    def test_same_text_menu_across_input_or_changed_menu_is_not_joined(self):
        renderer = AurigaRenderer()
        for barrier in ('input', 'different', 'cutin'):
            with self.subTest(barrier=barrier):
                # Two occurrences only: the intervening barrier must prevent a fold.
                item = returning_menu(barrier=barrier, answers=('help',))
                code = renderer.render(item)
                self.assertNotIn('while (1)', code)
                self.assertNotIn('continue;', code)
                self.assertEqual(code.count("switch ('@menu)"), 2)
                self.assertIn('mes "bye";', code)
                if barrier == 'input':
                    self.assertIn('入力数: 0', code)
        item = returning_menu(answers=('help',))
        final_menu = max(i for i, step in enumerate(item.steps) if step['kind'] == 'menu')
        item.steps = item.steps[:final_menu + 1]
        item.steps[-1]['reply'] = None
        item.status = 'observing'
        code = renderer.render(item)
        self.assertNotIn('while (1)', code)
        self.assertIn('応答未観測', code)

    def test_resource_differences_keep_switch_but_identical_observations_can_share_body(self):
        for same in (False, True):
            with self.subTest(same=same):
                first, second = simple(1), simple(2)
                for item, amount in ((first, 1), (second, 1 if same else 2)):
                    item.resource_observations = [dict(kind='item_gain', fields=dict(item_id=501, amount=amount, index=2),
                        direction='RECV', capture_session=item.capture_session, flow_id=item.flow_id,
                        cause_confirmed=False, timestamp=item.started, packet_index=4, packet_id=0xb41,
                        connection='half', source='NPCAP')]
                report, code = merged(first, second)
                self.assertEqual("switch ('@menu)" in code, not same)
                self.assertIn('NPC起因', code)
                self.assertNotIn('getitem ', code)
    def test_npc_file_wraps_single_and_merged_bodies_without_changing_structure(self):
        renderer = AurigaRenderer()
        first, second = simple(1, value=7), simple(2, value=8)
        group = build_merged([('a', first), ('b', second)])['groups'][0]
        for selected in (None, group):
            body = renderer.render_merged(selected) if selected is not None else renderer.render(first)
            result = renderer.render_npc_file(first, selected)
            self.assertIn('test.gat,10,20,0\tscript\t案内人\t45,{/*', result)
            self.assertIn('\n'.join('    ' + line for line in body.rstrip('\n').split('\n')), result)
            self.assertTrue(result.endswith('}\n'))
            self.assertNotIn('OnTouch', result)
            self.assertNotIn('OnTimer', result)

    def test_npc_file_rejects_unknown_placement_and_declaration_injection(self):
        renderer = AurigaRenderer()
        for key, value in (('map_name', ''), ('x', None), ('x', True), ('y', -1), ('direction', 8),
                           ('class_id', 65536), ('map_name', 'map\nscript'), ('name', 'a\tb'),
                           ('name', 'a::{evil}'), ('name', 'a//b'), ('name', 'あ' * 12)):
            with self.subTest(key=key, value=value):
                item = simple()
                item.npc[key] = value
                with self.assertRaises(ValueError):
                    renderer.render_npc_file(item)
    def test_immediate_divergence_keeps_both_opening_messages_in_root_blocks(self):
        _, code = merged(simple(opening='opening A'), simple(opening='opening B'))
        self.assertIn('{\n    mes "opening A";', code)
        self.assertIn('{\n    mes "opening B";', code)
        self.assertNotIn('goto ', code)
        self.assertNotIn('if (', code)

    def test_single_option_has_no_switch_or_named_label(self):
        item = simple(options=('continue',))
        for code in (AurigaRenderer().render(item), merged(item)[1]):
            self.assertIn('menu "continue";', code)
            self.assertNotIn('switch', code)
            self.assertNotIn('goto ', code)
            self.assertIn('mes "answer";', code)

    def test_all_options_observed_with_identical_complete_suffix_use_one_body(self):
        first, second = simple(1), simple(2)
        report, code = merged(first, second)
        self.assertEqual(report['groups'][0]['menus'][0]['observed'], [1, 2])
        self.assertIn('menu "one","two";', code)
        self.assertNotIn('switch', code)
        self.assertEqual(code.count('mes "answer";'), 1)

    def test_partial_observation_never_claims_all_choices_are_identical(self):
        _, code = merged(simple(1))
        self.assertIn("switch ('@menu) {", code)
        self.assertIn('    case 1:', code)
        self.assertIn('    case 2:', code)
        self.assertIn('未観測の分岐', code)
        self.assertEqual(code.count('break;'), 0)

    def test_same_first_line_but_different_suffix_remains_switch(self):
        first, second = simple(1), simple(2)
        extra = copy.deepcopy(second.steps[-2])
        extra['fields']['text'] = 'different later message'
        second.steps.insert(-1, extra)
        _, code = merged(first, second)
        self.assertIn("switch ('@menu)", code)
        self.assertIn('different later message', code)

    def test_unresolved_map_boundaries_do_not_prove_identical_complete_responses(self):
        first, second = simple(1), simple(2)
        for item in (first, second):
            item.steps.pop()
            item.status = 'map_changed'
            item.termination = dict(packet_index=99, packet_id=0x91, timestamp=2, connection='half', direction='RECV')
        _, code = merged(first, second)
        self.assertIn("switch ('@menu)", code)

    def test_numeric_input_variants_continue_in_annotated_blocks(self):
        report, code = merged(simple(options=(), value=12, answer='number A'),
                              simple(options=(), value=-7, answer='number B'))
        self.assertEqual(len(report['groups'][0]['inputs']), 1)
        self.assertIn('// 入力数: 12\n{\n    mes "number A";', code)
        self.assertIn('// 入力数: -7\n{\n    mes "number B";', code)
        self.assertNotIn('switch', code)
        self.assertNotIn('if (', code)

    def test_text_input_is_escaped_inside_a_single_comment_line(self):
        value = 'x";\n} // test'
        item = simple(options=(), value=value, text_input=True, answer='after input')
        for code in (AurigaRenderer().render(item), merged(item)[1]):
            self.assertIn('// 入力文字: "x\\";\\n} // test"\n{', code)
            self.assertIn('    mes "after input";', code)
            self.assertNotIn('\n} // test', code)

    def test_nested_switch_and_input_blocks_have_balanced_indentation(self):
        item = conversation(nested=True, input_prompt=True)
        _, code = merged(item)
        self.assertEqual(code.count("switch ('@menu)"), 2)
        self.assertIn("        switch ('@menu)", code)
        self.assertIn('                // 入力数: 1\n                {', code)
        self.assertIn('                    mes "one result";', code)
        openings = sum(line.strip() == '{' or line.strip().startswith('switch ') for line in code.splitlines())
        closings = sum(line.strip() == '}' for line in code.splitlines())
        self.assertEqual(openings, closings)

    def test_legacy_profile_inherits_new_structure_and_custom_indent_is_used(self):
        item = simple(options=(), value=1)
        with tempfile.TemporaryDirectory() as folder:
            document = json.loads(DEFAULT_DIALOGUE_PROFILE.read_text(encoding='utf-8'))
            from reconstruction.auriga import RESOURCE_FIELDS
            for key in set(STYLE_FIELDS) | set(PRESENTATION_FIELDS) | set(FILE_FIELDS) | set(RESOURCE_FIELDS):
                del document[key]
            path = Path(folder) / 'legacy.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertIn('// 入力数: 1\n{\n    mes ', AurigaRenderer(path).render(item))
            self.assertEqual(AurigaRenderer(path).templates['emotion'], 'emotion {value};')
            self.assertIn('\tscript\t案内人\t45,{/*', AurigaRenderer(path).render_npc_file(item))
            document['sound'] = '{sound.__class__}'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(ValueError):
                AurigaRenderer(path)
            del document['sound']
            document['indent'] = '  '
            path.write_text(json.dumps(document), encoding='utf-8')
            self.assertIn('// 入力数: 1\n{\n  mes ', AurigaRenderer(path).render(item))
            document['indent'] = '\n'
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaises(ValueError):
                AurigaRenderer(path)


if __name__ == '__main__':
    unittest.main()
