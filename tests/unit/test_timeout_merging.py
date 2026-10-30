from copy import deepcopy
import struct
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.branches import build_merged
from reconstruction.auriga import AurigaRenderer
from reconstruction.npc_bundle import build_npc_bundle
from tests.support.dialogue import packet
from tests.support.branches import NPC


def trial(prompt=0xb5, complete=False, identifier=1, layouts=()):
    prompts = {0xb5: b'', 0xb7: b'one:two:\0', 0x142: b'', 0x1d4: b'', 0xb6: b''}
    replies = {0xb5: (0xb9, b''), 0xb7: (0xb8, b'\1'), 0x142: (0x143, struct.pack('<i', 7)),
               0x1d4: (0x1d5, b'text\0'), 0xb6: (0x146, b'')}
    store = DialogueStore()
    events = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
              packet(0xb4, struct.pack('<I', 42) + b'hello\0'), packet(prompt, struct.pack('<I', 42) + prompts[prompt])]
    events.extend(packet(pid,body) for pid,body in layouts)
    if complete:
        reply, data = replies[prompt]
        events.append(packet(reply, struct.pack('<I', 42) + data, 'SEND'))
        if prompt == 0xb6:
            events.append(packet(0x1b3, b'portrait.bmp'.ljust(64, b'\0') + b'\x02'))
        else:
            events.extend([packet(0xb4, struct.pack('<I', 42) + b'continued\0'), packet(0xb6, struct.pack('<I', 42))])
    else:
        events.append(packet(0xb6, struct.pack('<I', 42)))
    for event in events:
        store.apply(event)
    item = store.sessions[0]
    item.id, item.npc = identifier, dict(NPC)
    return item


def executable(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('//')]


def resource_trial(complete=False, identifier=1, state=0, zeny=1000, reverse=False, omit=False):
    from tests.unit.test_quest_observations import addition
    store = DialogueStore()
    for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'), addition()):
        store.apply(event)
    observations = [(packet(0x2b7, struct.pack('<IB', 12345, state)), None),
        (packet(0xb1, struct.pack('<HI', 20, zeny)), dict(event_kind='zeny', zeny=zeny, delta=10, delta_known=True))]
    if omit:
        observations.pop()
    for event, values in reversed(observations) if reverse else observations:
        store.apply(event, player_observation=values)
    store.apply(packet(0xb5, struct.pack('<I', 42)))
    if complete:
        store.apply(packet(0xb9, struct.pack('<I', 42), 'SEND'))
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'continued\0'))
    store.apply(packet(0xb6, struct.pack('<I', 42)))
    item = store.sessions[0]
    item.id, item.npc = identifier, dict(NPC)
    return item


class TimeoutMergingTests(unittest.TestCase):
    def test_identical_pre_prompt_resource_evidence_normalizes_without_duplicate_quest_command(self):
        partial, full = resource_trial(), resource_trial(True, 2)
        before = deepcopy((partial, full))
        report = build_merged([('partial', partial), ('full', full)])
        self.assertFalse(report['excluded'])
        group = report['groups'][0]
        self.assertEqual(group['timeout_normalizations'][0]['matched_resource_observations'], 3)
        code = AurigaRenderer().render_merged(group)
        baseline = AurigaRenderer().render_merged(build_merged([('full', full)])['groups'][0])
        self.assertEqual(executable(code), executable(baseline))
        self.assertEqual(code.count('setquest 12345;'), 1)
        self.assertEqual((partial, full), before)
        self.assertEqual(report, build_merged([('full', full), ('partial', partial)]))

    def test_pre_prompt_state_value_count_and_order_differences_remain_unmatched(self):
        full = resource_trial(True, 2)
        for partial in (resource_trial(state=1), resource_trial(zeny=900), resource_trial(reverse=True), resource_trial(omit=True)):
            report = build_merged([('partial', partial), ('full', full)])
            self.assertEqual(report['excluded'][0]['reason'], 'timeout_prefix_unmatched')
            self.assertFalse(report['groups'][0]['timeout_normalizations'])

    def test_unanswered_close_prefixes_absorb_into_observed_continuation_without_terminal_branch(self):
        for prompt in (0xb5, 0xb7, 0x142, 0x1d4, 0xb6):
            partial, full = trial(prompt), trial(prompt, True, 2)
            before = deepcopy((partial, full))
            baseline = build_merged([('full', full)])['groups'][0]
            merged = build_merged([('partial', partial), ('full', full)])
            self.assertFalse(merged['excluded'])
            self.assertEqual(len(merged['groups']), 1)
            group = merged['groups'][0]
            self.assertEqual(len(group['contributions']), 2)
            self.assertEqual(len(group['timeout_normalizations']), 1)
            self.assertFalse(any(node['kind'] in ('timeout_warning', 'aborted_wait', 'pending') for node in group['nodes']))
            renderer = AurigaRenderer()
            self.assertEqual(executable(renderer.render_merged(group)), executable(renderer.render_merged(baseline)))
            bundle = build_npc_bundle([], [partial, full], {'0': 'source'}, merge=True)
            self.assertEqual(len(bundle['entries']), 1)
            self.assertNotIn('ここで終了しclose2', bundle['auriga'])
            self.assertEqual((partial, full), before)

    def test_unmatched_or_additional_timeout_evidence_stays_outside_normalization(self):
        partial, full = trial(), trial(complete=True, identifier=2)
        partial.steps[1]['fields']['text'] = 'different'
        report = build_merged([('partial', partial), ('full', full)])
        self.assertEqual(report['excluded'][0]['reason'], 'timeout_prefix_unmatched')
        self.assertFalse(report['groups'][0]['timeout_normalizations'])
        partial = trial()
        partial.resource_observations.append(dict(kind='quest_state', fields={'quest_id': 1, 'state': 0},
            capture_session=0, flow_id='flow', cause_confirmed=False, direction='RECV', timestamp=1,
            packet_index=2, packet_id=0x2b7, connection='half', source='NPCAP', after_step_index=2))
        report = build_merged([('partial', partial), ('full', full)])
        self.assertEqual(report['excluded'][0]['reason'], 'timeout_additional_evidence_review')
        only = build_merged([('partial', trial())])
        self.assertFalse(only['groups'])
        self.assertEqual(only['excluded'][0]['reason'], 'timeout_prefix_unmatched')

    def test_normalization_is_order_independent_and_does_not_count_partial_as_repeat_trial(self):
        partial, full = trial(), trial(complete=True, identifier=2)
        pairs = [('partial', partial), ('full', full)]
        self.assertEqual(build_merged(pairs), build_merged(reversed(pairs)))
        group = build_merged(pairs)['groups'][0]
        self.assertEqual(sum(row.get('partial_observation', False) for row in group['contributions']), 1)
        self.assertEqual(group['presentation_check']['conflicts'], 0)


    def test_matching_wait_layouts_normalize_without_duplicate_commands_for_all_input_kinds(self):
        layouts=((0xba2,struct.pack('<II',180,280)),(0xba3,struct.pack('<II',10,20)),(0xba1,b'\x01'))
        for prompt in (0xb5,0xb7,0x142,0x1d4):
            with self.subTest(prompt=prompt):
                partial,full=trial(prompt,layouts=layouts),trial(prompt,True,2,layouts)
                before=deepcopy((partial,full))
                pairs=[('partial',partial),('full',full)]
                report=build_merged(pairs)
                self.assertFalse(report['excluded'])
                self.assertEqual(len(report['groups']),1)
                group=report['groups'][0]
                self.assertEqual(group['timeout_normalizations'][0]['matched_wait_layout_observations'],3)
                self.assertEqual(group['presentation_check']['conflicts'],0)
                code=AurigaRenderer().render_merged(group)
                baseline=AurigaRenderer().render_merged(build_merged([('full',full)])['groups'][0])
                self.assertEqual(executable(code),executable(baseline))
                for command in ('messize 180,280;','mespos 10,20;','mesalign 1;'):
                    self.assertEqual(code.count(command),1)
                self.assertEqual(report,build_merged(reversed(pairs)))
                self.assertEqual((partial,full),before)
                self.assertNotIn('messize',AurigaRenderer().render(partial))

    def test_wait_layout_differences_or_invalid_order_do_not_normalize(self):
        layouts=((0xba2,struct.pack('<II',180,280)),(0xba1,b'\x01'))
        full=trial(complete=True,identifier=2,layouts=layouts)
        alternatives=((),tuple(reversed(layouts)),(layouts[0],),
                      ((0xba2,struct.pack('<II',180,320)),layouts[1]),layouts+(layouts[1],))
        for changed in alternatives:
            partial=trial(layouts=changed)
            report=build_merged([('partial',partial),('full',full)])
            self.assertEqual(report['excluded'][0]['reason'],'timeout_prefix_unmatched')
            self.assertFalse(report['groups'][0]['timeout_normalizations'])
        for defect in ('after_close','duplicate','wrong_packet','wrong_flow','time_reversed'):
            partial=trial(layouts=layouts)
            if defect=='after_close':partial.actions[0]['packet_index']=partial.steps[-1]['packet_index']+1
            elif defect=='duplicate':partial.actions[1]['packet_index']=partial.actions[0]['packet_index']
            elif defect=='wrong_packet':partial.actions[0]['packet_id']=0xba1
            elif defect=='time_reversed':
                partial.started=0
                for index,step in enumerate(partial.steps):step['timestamp']=index
                partial.actions[0]['timestamp']=2.8
                partial.actions[1]['timestamp']=2.2
            else:partial.actions[0]['flow_id']='other'
            report=build_merged([('partial',partial),('full',full)])
            self.assertTrue(report['excluded'])
            self.assertFalse(report['groups'][0]['timeout_normalizations'])
