from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.quests import decode_quest, ADD_LENGTHS, COUNT_LAYOUTS
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from tests.support.branches import NPC
from tests.support.dialogue import packet


def addition(pid=0xb0c, count=2):
    return packet(pid, struct.pack('<IBIIH', 12345, 1, 0, 999, count) + bytes(ADD_LENGTHS[pid] - 17))


def counter(pid=0xafe, rows=1):
    header, stride, _ = COUNT_LAYOUTS[pid]
    records = b''
    for index in range(rows):
        records += (struct.pack('<IIIHH', 12345, 54321, index, 10, 65535) if stride == 16 else
                    struct.pack('<IIHH', 12345, 54321 + index, 10, 65535))
    return packet(pid, struct.pack('<H', header + len(records)) +
                  (struct.pack('<H', rows) if header == 6 else b'') + records)


class QuestObservationTests(unittest.TestCase):
    def test_post_close_quest_uses_original_ack_window_and_does_not_attach_before_ack_or_other_flow(self):
        def closed():
            store = DialogueStore()
            for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                          packet(0xb4, struct.pack('<I', 42) + b'hello\0'), packet(0xb6, struct.pack('<I', 42))):
                store.apply(event)
            return store
        store = closed()
        store.apply(packet(0x146, struct.pack('<I', 42), 'SEND', timestamp=1))
        store.apply(replace(addition(), timestamp=2.5))
        store.apply(packet(0x2b4, struct.pack('<I', 12345), timestamp=3.1))
        item = store.sessions[0]
        code = AurigaRenderer().render(item)
        self.assertIn('close2;', code)
        self.assertLess(code.index('close2;'), code.index('setquest 12345;'))
        self.assertLess(code.index('setquest 12345;'), code.rindex('end;'))
        self.assertNotIn('\ndelquest ', code)
        self.assertEqual(len(item.resource_observations), 1)
        self.assertEqual(store.quest_observations[-1]['context'], 'outside_dialogue')
        for ack, flow in ((False, 'flow'), (True, 'other')):
            store = closed()
            if ack:
                store.apply(packet(0x146, struct.pack('<I', 42), 'SEND'))
            store.apply(replace(addition(), flow_id=flow))
            self.assertFalse(store.sessions[0].resource_observations)
            self.assertNotIn('close2;', AurigaRenderer().render(store.sessions[0]))

    def test_repeated_menu_keeps_quest_side_effects_inside_while_and_before_return(self):
        store = DialogueStore()
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0xb7, struct.pack('<I', 42) + b'again:exit:\0'),
                      packet(0xb8, struct.pack('<IB', 42, 1), 'SEND'), addition(),
                      packet(0xb7, struct.pack('<I', 42) + b'again:exit:\0'),
                      packet(0xb8, struct.pack('<IB', 42, 2), 'SEND'),
                      packet(0x2b4, struct.pack('<I', 12345)), packet(0xb6, struct.pack('<I', 42))):
            store.apply(event)
        item = store.sessions[0]
        item.npc = dict(NPC)
        before = deepcopy(item)
        for code in (AurigaRenderer().render(item),
                     AurigaRenderer().render_merged(build_merged([('log', item)])['groups'][0])):
            self.assertIn('while (1)', code)
            self.assertLess(code.index('while (1)'), code.index('setquest 12345;'))
            self.assertLess(code.index('setquest 12345;'), code.index('continue;'))
            self.assertIn('delquest 12345;', code)
            self.assertEqual(code.count('setquest 12345;'), 1)
        self.assertEqual(item, before)

    def test_counter_versions_preserve_objective_namespace_received_counts_and_dialogue_comments(self):
        for pid, (_, stride, objective_kind) in COUNT_LAYOUTS.items():
            for count in (0, 1, 3):
                kind, fields = decode_quest(counter(pid, count))
                self.assertEqual(kind, 'quest_count')
                self.assertEqual(fields['objective_kind'], objective_kind)
                self.assertEqual(fields['entry_count'], count)
                for index, row in enumerate(fields['entries']):
                    self.assertEqual(row['current_count'], 65535)
                    self.assertEqual(row['required_count'], 10)
                    self.assertEqual('objective_index' in row, stride == 16)
                    if stride == 16:
                        self.assertEqual(row['objective_index'], index)
            store = DialogueStore()
            store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
            store.apply(counter(pid))
            store.apply(packet(0xb6, struct.pack('<I', 42)))
            item = store.sessions[0]
            item.npc = dict(NPC)
            code = AurigaRenderer().render(item)
            self.assertIn('クエスト目標更新', code)
            self.assertIn('65535', code)
            self.assertFalse(build_merged([('log', item)])['excluded'])

    def test_counter_invalid_lengths_counts_and_flow_do_not_partially_attach_entries(self):
        for pid in COUNT_LAYOUTS:
            good = counter(pid)
            for event in (replace(good, raw=good.raw[:-1]), counter(pid, 4)):
                with self.assertRaises(ValueError):
                    decode_quest(event)
            if COUNT_LAYOUTS[pid][0] == 6:
                damaged = bytearray(good.raw)
                struct.pack_into('<H', damaged, 4, 2)
                with self.assertRaises(ValueError):
                    decode_quest(replace(good, raw=bytes(damaged)))
            self.assertIsNone(decode_quest(replace(good, direction='SEND')))
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(replace(counter(), flow_id='another-flow'))
        self.assertFalse(store.sessions[0].resource_observations)
        self.assertEqual(store.quest_observations[0]['context'], 'outside_dialogue')
        self.assertEqual(len(store.sessions), 1)
    def test_versioned_add_delete_state_preserve_payload_and_do_not_create_or_close_dialogue(self):
        store = DialogueStore()
        for pid in ADD_LENGTHS:
            store.apply(addition(pid))
        self.assertEqual(len(store.quest_observations), 3)
        self.assertFalse(store.sessions)
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb5, struct.pack('<I', 42)))
        for event in (addition(), packet(0x2b7, struct.pack('<IB', 12345, 255)),
                      packet(0x2b4, struct.pack('<I', 12345))):
            store.apply(event)
        store.apply(packet(0xb9, struct.pack('<I', 42), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        item.npc = dict(NPC)
        self.assertEqual(store.issue_count, 0)
        self.assertEqual(item.steps[2]['reply_to'], 1)
        self.assertEqual([row['kind'] for row in item.resource_observations], ['quest_add', 'quest_state', 'quest_delete'])
        self.assertEqual(len(item.resource_observations[0]['fields']['objective_payload_hex']), 276)
        self.assertEqual(item.resource_observations[1]['fields']['state'], 255)
        before = deepcopy(item)
        code = AurigaRenderer().render(item)
        self.assertIn('クエスト追加 ID=12345', code)
        self.assertIn('クエスト削除 ID=12345', code)
        self.assertIn('setquest 12345;', code)
        self.assertIn('delquest 12345;', code)
        self.assertFalse(any(line.strip().startswith('if ') for line in code.splitlines()))
        self.assertFalse(build_merged([('log', item)])['excluded'])
        self.assertEqual(item, before)

    def test_quest_commands_keep_path_order_merge_branches_and_defer_waiting_notifications(self):
        trials = []
        for choice in (1, 2):
            store = DialogueStore()
            for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'), addition(),
                          packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                          packet(0xb7, struct.pack('<I', 42) + b'one:two:\0'),
                          packet(0xb8, struct.pack('<IB', 42, choice), 'SEND'),
                          packet(0x2b4, struct.pack('<I', 12345 if choice == 1 else 54321)),
                          packet(0xb4, struct.pack('<I', 42) + b'result\0'), packet(0xb6, struct.pack('<I', 42))):
                store.apply(event)
            item = store.sessions[0]
            item.npc = dict(NPC)
            code = AurigaRenderer().render(item)
            self.assertLess(code.index('\nsetquest 12345;'), code.index('\nmes "hello";'))
            self.assertLess(code.index(f'delquest {12345 if choice == 1 else 54321};'), code.index('mes "result";'))
            trials.append((str(choice), item))
        group = build_merged(trials)['groups'][0]
        code = AurigaRenderer().render_merged(group)
        self.assertEqual(code.count('setquest 12345;'), 1)
        self.assertIn('delquest 12345;', code)
        self.assertIn('delquest 54321;', code)
        self.assertNotIn('checkquest(', code)
        waiting = DialogueStore()
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'), packet(0xb5, struct.pack('<I', 42)), addition()):
            waiting.apply(event)
        self.assertNotIn('\nsetquest ', AurigaRenderer().render(waiting.sessions[0]))
        waiting.apply(packet(0xb9, struct.pack('<I', 42), 'SEND'))
        waiting.apply(packet(0xb6, struct.pack('<I', 42)))
        deferred = AurigaRenderer().render(waiting.sessions[0])
        self.assertLess(deferred.index('next;'), deferred.index('setquest 12345;'))
        self.assertIn('入力待ち中のクエスト通知', deferred)

    def test_bad_lengths_counts_directions_and_capacity_keep_evidence_honest(self):
        for event in (replace(addition(), raw=addition().raw[:-1]), addition(count=4),
                      packet(0x2b4, b'bad'), packet(0x2b7, bytes(4))):
            with self.assertRaises(ValueError):
                decode_quest(event)
        self.assertIsNone(decode_quest(replace(addition(), direction='SEND')))
        store = DialogueStore(max_presentations=1)
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(addition())
        store.apply(addition())
        self.assertEqual(len(store.quest_observations), 1)
        self.assertEqual(store.quest_dropped, 1)
        self.assertEqual(len(store.sessions[0].resource_observations), 1)
        self.assertTrue(store.sessions[0].issues)
        store.apply(packet(0x2b4, b'bad'))
        self.assertEqual(len(store.sessions), 1)
        self.assertEqual(store.sessions[0].issues[-1]['message'], 'Invalid quest notification')
