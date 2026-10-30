from tests.support.dialogue import packet
import json
from pathlib import Path
import struct
import tempfile
import unittest

from reconstruction.auriga import AurigaRenderer, DEFAULT_DIALOGUE_PROFILE
from reconstruction.dialogue import DialogueStore
from capture.receiver import Receiver
from reconstruction.world import WorldStore
from tests.support.world import actor_packet
from dataclasses import replace




class DialogueTests(unittest.TestCase):
    def test_trailing_empty_menu_slots_preserve_original_text_and_reply_numbers(self):
        from reconstruction.dialogue import decode_dialogue
        from reconstruction.decoder import ObservationError
        for trailing in ('', ':', ':::::', '::::::::'):
            for choice in (1, 2, 3):
                with self.subTest(trailing=len(trailing), choice=choice):
                    self.store = DialogueStore()
                    self.open()
                    text = 'one:two:three' + trailing
                    event = self.apply(0xb7, struct.pack('<I', 42) + text.encode() + b'\0')
                    self.apply(0xb8, struct.pack('<IB', 42, choice), 'SEND')
                    self.apply(0xb4, struct.pack('<I', 42) + b'result\0')
                    self.apply(0xb6, struct.pack('<I', 42))
                    item = self.store.sessions[0]
                    self.assertEqual(item.steps[1]['fields']['text'], text)
                    self.assertEqual(item.steps[1]['fields']['options'], ['one', 'two', 'three'])
                    self.assertEqual(item.steps[2]['reply_to'], 1)
                    self.assertEqual(item.steps[2]['fields']['value'], choice)
                    self.assertEqual(event.raw[8:-1], text.encode())
                    self.assertIn('menu "one:two:three",-;', AurigaRenderer().render(item))
                    self.assertFalse(item.issues)
        for text in ('', '::::', ':one:two:', 'one::two::::', ':'.join(['one'] * 255)):
            with self.subTest(text_length=len(text)), self.assertRaises(ObservationError):
                decode_dialogue(packet(0xb7, struct.pack('<I', 42) + text.encode() + b'\0'))
        self.store = DialogueStore()
        self.open()
        self.apply(0xb7, struct.pack('<I', 42) + b'one:two:::::\0')
        self.apply(0xb8, struct.pack('<IB', 42, 3), 'SEND')
        self.assertNotIn('reply', self.store.sessions[0].steps[1])
        self.assertTrue(self.store.sessions[0].issues)

    def test_open_without_dialogue_content_is_a_pending_candidate(self):
        self.open()
        for dismissed in (False, True):
            if dismissed:
                self.apply(0x146, struct.pack('<I', 42), 'SEND')
            code = AurigaRenderer().render(self.store.sessions[0])
            self.assertIn('応答未観測', code)
            self.assertNotIn('mes ', code)
    def test_resource_observations_preserve_input_links_and_unknown_balance(self):
        from reconstruction.player import PlayerStore
        from tests.support.player import pickup
        from reconstruction.timing import build_timeline
        players = PlayerStore()
        def consume(event):
            index = self.store.packet_ordinal
            values = players.apply(event, packet_index=index)
            self.store.apply(event, packet_index=index, player_observation=values)
        events = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0x142, struct.pack('<I', 42)),
                  packet(0xb1, struct.pack('<HI', 20, 1000)),
                  packet(0xb1, struct.pack('<HI', 20, 800)),
                  replace(pickup(), flow_id='flow', connection='half', timestamp=1),
                  packet(0xaf, struct.pack('<HH', 2, 1)),
                  packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'continued\0'),
                  packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20))]
        for event in events:
            consume(event)
        item = self.store.sessions[0]
        self.assertEqual(item.status, 'map_changed')
        self.assertEqual(item.steps[2]['reply_to'], 1)
        observations = item.resource_observations
        self.assertEqual([row['kind'] for row in observations], ['zeny', 'zeny', 'item_gain', 'item_loss', 'map'])
        self.assertFalse(observations[0]['fields']['delta_known'])
        self.assertEqual(observations[1]['fields']['delta'], -200)
        self.assertEqual(observations[3]['fields']['item_id'], 501)
        self.assertTrue(all(not row['cause_confirmed'] for row in observations))
        code = AurigaRenderer().render(item)
        self.assertIn('差分不明', code)
        self.assertIn('観測差分 -200', code)
        self.assertIn('アイテム 501 -1', code)
        self.assertIn('// 入力数: 7\n{\n', code)
        self.assertIn('    getitem 501,3;', code)
        self.assertIn('    delitem 501,1;', code)
        self.assertLess(code.index('getitem 501,3;'), code.index('delitem 501,1;'))
        self.assertLess(code.index('delitem 501,1;'), code.index('mes "continued";'))
        self.assertNotIn('warp ', code)
        timeline = build_timeline(item)
        self.assertEqual(sum(row.get('track') == 'resource_observation' for row in timeline['rows']), 4)
        self.assertTrue(any(row['packet_index'] == 3 for row in timeline['rows']))
        # Closed/boundary and unrelated-flow changes cannot be assigned to this NPC.
        consume(packet(0xb1, struct.pack('<HI', 20, 700)))
        self.assertEqual(len(item.resource_observations), 5)
        consume(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        second = self.store.sessions[-1]
        consume(packet(0xb1, struct.pack('<HI', 20, 10), flow='other'))
        consume(replace(pickup(result=255), flow_id='flow', connection='half', timestamp=1))
        consume(packet(0xaf, struct.pack('<HH', 999, 1)))
        consume(packet(0xb1, struct.pack('<HI', 20, 700)))
        self.assertFalse(second.resource_observations)
        self.store.resource_count = 10000
        consume(packet(0xb1, struct.pack('<HI', 20, 600)))
        self.assertFalse(second.resource_observations)
        self.assertEqual(second.issues[-1]['message'], 'Resource observation capacity reached')

    def setUp(self):
        self.store = DialogueStore()

    def apply(self, pid, data=b'', direction='RECV', **kwargs):
        event = packet(pid, data, direction, **kwargs)
        self.store.apply(event)
        return event

    def open(self, actor=42, **kwargs):
        self.apply(0x90, struct.pack('<IB', actor, 1), 'SEND', **kwargs)

    def menu(self):
        self.apply(0xb7, struct.pack('<I', 42) + b'one:two:\0')

    def test_selected_branch_and_external_profile(self):
        self.open(connection='send SYN 1')
        self.menu()
        self.apply(0xb8, struct.pack('<IB', 42, 2), 'SEND', connection='send SYN 1')
        self.apply(0xb4, struct.pack('<I', 42) + b'hello "x"\\\0')
        self.apply(0xb6, struct.pack('<I', 42))
        conversation = self.store.sessions[0]
        self.assertEqual(conversation.status, 'closed')
        self.assertEqual(conversation.steps[2]['reply_to'], 1)
        code = AurigaRenderer().render(conversation)
        self.assertIn('menu "one:two",-;', code)
        self.assertIn('switch (@menu) {', code)
        self.assertIn('    case 1:\n        // 未観測の分岐', code)
        self.assertIn('    case 2:\n        mes ', code)
        self.assertNotIn('GPA_', code)
        self.assertIn('mes "hello \\"x\\"\\\\";', code)
        with tempfile.TemporaryDirectory() as folder:
            profile = json.loads(DEFAULT_DIALOGUE_PROFILE.read_text(encoding='utf-8'))
            profile['mes'] = '// custom\nmes {text};'
            path = Path(folder) / 'dialogue.json'
            path.write_text(json.dumps(profile), encoding='utf-8')
            self.assertIn('// custom', AurigaRenderer(path).render(conversation))
            profile['mes'] = '{text.__class__}'
            path.write_text(json.dumps(profile), encoding='utf-8')
            with self.assertRaises(ValueError):
                AurigaRenderer(path)

    def test_unseen_and_invalid_choices_never_claim_a_branch(self):
        for value in (None, 0, 3, 255):
            self.store = DialogueStore()
            self.open()
            self.menu()
            if value is not None:
                self.apply(0xb8, struct.pack('<IB', 42, value), 'SEND')
            code = AurigaRenderer().render(self.store.sessions[0])
            self.assertNotIn('goto GPA_', code)
            self.assertEqual(code.count('未観測の分岐'), 2)

    def test_prompts_input_cutin_and_close(self):
        self.open()
        self.apply(0xb5, struct.pack('<I', 42))
        self.apply(0xb9, struct.pack('<I', 42), 'SEND')
        self.apply(0x142, struct.pack('<I', 42))
        self.apply(0x143, struct.pack('<Ii', 42, -3), 'SEND')
        self.apply(0x1d4, struct.pack('<I', 42))
        self.apply(0x1d5, struct.pack('<I', 42) + b'abc\0', 'SEND')
        self.apply(0x1b3, b'portrait'.ljust(64, b'\0') + b'\x00')
        self.apply(0xb6, struct.pack('<I', 42))
        code = AurigaRenderer().render(self.store.sessions[0])
        self.assertIn('next;', code)
        self.assertIn("input '@gpa_number;", code)
        self.assertIn("input '@gpa_text$;", code)
        self.assertIn('close;', code)
        self.assertNotIn('close2;', code)
        self.assertIn('// 入力数: -3\n{', code)
        self.assertIn('// 入力文字: "abc"\n    {', code)
        self.assertNotIn('if (', code)

    def test_partial_capture_bounds_invalid_text_and_safe_issues(self):
        self.apply(0xb4, struct.pack('<I', 42) + b'hello\0')
        self.assertFalse(self.store.sessions[0].observed_open)
        self.apply(0xb4, struct.pack('<I', 42) + b'\x81')
        self.assertEqual(self.store.issue_count, 1)
        self.assertEqual(self.store.sessions[0].status, 'decode_error')
        self.assertNotIn('hello', json.dumps(list(self.store.issues)))
        self.apply(0xb4)
        self.assertEqual(self.store.issue_count, 2)

    def test_flow_actor_capture_and_map_isolation(self):
        self.open()
        self.open(flow='other')
        self.open(actor=43)
        self.assertEqual(len(self.store.sessions), 3)
        self.assertEqual(self.store.sessions[0].status, 'interrupted')
        self.apply(0x91, bytes(20))
        self.assertEqual(self.store.sessions[-1].status, 'map_changed')
        self.store.begin_capture(1)
        self.assertEqual(self.store.sessions[1].status, 'capture_changed')
        self.open(flow='late')  # Older generation cannot reactivate current sessions.
        self.assertEqual(self.store.sessions[-1].status, 'past_capture')
        self.assertFalse(self.store.active)

    def test_step_capacity_and_reply_mismatch(self):
        self.store = DialogueStore(max_steps=2)
        self.open()
        self.menu()
        self.apply(0xb9, struct.pack('<I', 42), 'SEND')
        self.assertEqual(self.store.sessions[0].status, 'capacity_reached')
        self.assertEqual(self.store.step_count, 2)
        self.store = DialogueStore()
        self.open()
        self.menu()
        self.apply(0xb9, struct.pack('<I', 42), 'SEND')
        self.assertTrue(self.store.sessions[0].issues)
        self.assertNotIn('reply', self.store.sessions[0].steps[1])
        self.apply(0xb8, struct.pack('<IB', 999, 1), 'SEND')
        self.assertEqual(self.store.sessions[0].status, 'observing')
        self.assertEqual(len(self.store.sessions), 1)

    def test_transport_flow_shared_and_rotated_without_changing_raw(self):
        events = []
        receiver = Receiver('server', 1, {0x90: 7}, events.append, lambda _: None, capture_send=True)
        incoming = ('server', 1, 'client', 2)
        outgoing = receiver.reverse_key(incoming)
        receiver._consume(outgoing, 10, 2, b'', 1, 'SEND')
        receiver._consume(incoming, 30, 18, b'', 1, 'RECV')
        raw = struct.pack('<HIB', 0x90, 42, 1)
        receiver._consume(outgoing, 11, 16, raw, 2, 'SEND')
        receiver._consume(incoming, 31, 16, raw, 2, 'RECV')
        self.assertEqual(events[0].flow_id, events[1].flow_id)
        self.assertNotEqual(events[0].connection, events[1].connection)
        receiver._consume(outgoing, 80, 2, b'', 3, 'SEND')
        receiver._consume(outgoing, 81, 16, raw, 4, 'SEND')
        self.assertNotEqual(events[0].flow_id, events[-1].flow_id)
        self.assertEqual(events[-1].raw, raw)

    def test_npc_metadata_is_resolved_only_in_matching_flow(self):
        world = WorldStore()
        world.apply(replace(actor_packet(), flow_id='flow'))
        self.store = DialogueStore(world=world)
        self.open()
        self.assertEqual(self.store.sessions[0].npc['name'], '案内人')
        self.assertEqual(self.store.sessions[0].npc['x'], 150)
        self.open(flow='other')
        self.assertEqual(self.store.sessions[-1].npc, {})

    def test_close_ack_retains_evidence_without_another_conversation(self):
        self.open()
        self.apply(0xb6, struct.pack('<I', 42))
        self.apply(0x146, struct.pack('<I', 42), 'SEND')
        self.assertEqual(len(self.store.sessions), 1)
        self.assertEqual(self.store.sessions[0].steps[-1]['kind'], 'dismiss')
        self.assertEqual(self.store.issue_count, 0)
        self.assertFalse(self.store.active)

    def test_pending_prompt_stops_and_intervening_event_does_not_claim_branch(self):
        self.open()
        self.menu()
        self.apply(0xb4, struct.pack('<I', 42) + b'unattributed\0')
        self.apply(0xb8, struct.pack('<IB', 42, 1), 'SEND')
        code = AurigaRenderer().render(self.store.sessions[0])
        self.assertNotIn('goto GPA_', code)
        self.assertNotIn('unattributed', code)
        self.store = DialogueStore()
        self.open()
        self.apply(0xb5, struct.pack('<I', 42))
        self.apply(0xb4, struct.pack('<I', 42) + b'unattributed\0')
        self.assertNotIn('unattributed', AurigaRenderer().render(self.store.sessions[0]))

    def test_npc_presentations_preserve_evidence_and_target_scope(self):
        from reconstruction.branches import build_merged
        from tests.support.branches import NPC
        sound = b'voice"test.wav'.ljust(24, b'\0') + struct.pack('<BII', 1, 250, 42)
        # Standalone, other actors/flows and SEND cannot create or replace a dialogue.
        self.apply(0xc0, struct.pack('<IB', 42, 3))
        self.assertFalse(self.store.sessions)
        self.open()
        self.apply(0xc0, struct.pack('<IB', 99, 8))
        self.apply(0x1d3, sound, flow='other')
        self.apply(0xc0, struct.pack('<IB', 42, 9), 'SEND')
        self.apply(0xc0, struct.pack('<IB', 42, 3))
        self.apply(0x19b, struct.pack('<II', 99, 100))
        self.apply(0x1f3, struct.pack('<II', 99, 100))
        self.apply(0x1d3, sound)
        self.apply(0x19b, struct.pack('<II', 42, 99))
        self.apply(0x1f3, struct.pack('<II', 42, 100))
        self.menu()
        # A parallel effect while waiting must not move after the generated input.
        self.apply(0xc0, struct.pack('<IB', 42, 8))
        self.apply(0xb8, struct.pack('<IB', 42, 1), 'SEND')
        self.apply(0xb4, struct.pack('<I', 42) + b'answer\0')
        self.apply(0xb6, struct.pack('<I', 42))
        item = self.store.sessions[0]
        item.npc = dict(NPC)
        self.assertEqual([s['kind'] for s in item.steps],
                         ['open', 'emotion', 'sound', 'effect', 'effect', 'menu', 'choice', 'mes', 'close'])
        self.assertEqual(item.steps[2]['packet_index'], 8)
        self.assertEqual(item.steps[6]['reply_to'], 5)
        self.assertEqual(len(item.parallel_presentations), 1)
        self.assertEqual(item.parallel_presentations[0]['fields']['value'], 8)
        self.assertEqual(item.parallel_presentations[0]['prompt_step_index'], 5)
        group = build_merged([('source', item)])['groups'][0]
        for code in (AurigaRenderer().render(item), AurigaRenderer().render_merged(group)):
            self.assertIn('emotion 3;', code)
            self.assertIn('misceffect 99;', code)
            self.assertIn('misceffect 100;', code)
            self.assertIn('soundeffect "voice\\"test.wav",1,250;', code)
            self.assertNotIn('emotion 8;', code)
            self.assertIn('mes "answer";', code)
        self.assertEqual(self.store.issue_count, 0)

    def test_parallel_presentations_are_bounded_and_outside_events_never_open_dialogue(self):
        self.store = DialogueStore(max_presentations=1)
        self.apply(0xc0, struct.pack('<IB', 42, 1))
        self.assertFalse(self.store.sessions)
        self.assertEqual(self.store.presentation_observations[0]['context'], 'outside_dialogue')
        self.open()
        self.menu()
        self.apply(0xc0, struct.pack('<IB', 42, 2))
        self.assertEqual(self.store.presentation_dropped, 1)
        self.assertFalse(self.store.sessions[0].parallel_presentations)
        self.assertEqual(self.store.sessions[0].issues[-1]['message'], 'Parallel presentation capacity reached')
        snapshot = self.store.snapshot()
        snapshot['presentation_observations'][0]['fields']['value'] = 99
        self.assertEqual(self.store.presentation_observations[0]['fields']['value'], 1)

    def test_npc_presentation_layout_errors_are_bounded_and_private(self):
        for mode in (0, 1, 2):
            with self.subTest(mode=mode):
                self.store = DialogueStore()
                self.open()
                # Fixed-width names need not have a terminating NUL.
                self.apply(0x1d3, b'a' * 24 + struct.pack('<BII', mode, 250, 42))
                self.assertIn(f'soundeffect "{"a" * 24}",{mode},250;',
                              AurigaRenderer().render(self.store.sessions[0]))
        for body in (b'private.wav'.ljust(24, b'\0') + struct.pack('<BII', 9, 1, 42),
                     b'\x81\0'.ljust(24, b'\0') + struct.pack('<BII', 0, 1, 42),
                     b'private.wav'.ljust(24, b'\0') + struct.pack('<BII', 0, 1, 42) + b'extra'):
            with self.subTest(body_length=len(body)):
                self.store = DialogueStore()
                self.open()
                self.apply(0x1d3, body)
                self.assertEqual(self.store.sessions[0].status, 'decode_error')
                self.assertEqual(self.store.issue_count, 1)
                self.assertNotIn('private.wav', json.dumps(list(self.store.issues)))


if __name__ == '__main__':
    unittest.main()

