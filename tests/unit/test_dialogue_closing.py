import struct
import unittest
from copy import deepcopy

from reconstruction.auriga import AurigaRenderer
from reconstruction.dialogue import DialogueStore
from reconstruction.branches import build_merged
from tests.support.branches import NPC
from tests.support.dialogue import packet


class ClosingTests(unittest.TestCase):
    def test_late_input_replies_are_separate_evidence_before_or_after_dismissal_and_never_resume(self):
        for prompt_pid, suffix, reply_pid, reply_body in (
                (0xb5, b'', 0xb9, b''), (0xb7, b'one:two:\0', 0xb8, b'\x01'),
                (0x142, b'', 0x143, struct.pack('<i', 42)), (0x1d4, b'', 0x1d5, b'late\0')):
            for ack_first in (False, True):
                store = DialogueStore()
                for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                              packet(prompt_pid, struct.pack('<I', 42) + suffix), packet(0xb6, struct.pack('<I', 42))):
                    store.apply(event)
                if ack_first:
                    store.apply(self.ack())
                store.apply(packet(reply_pid, struct.pack('<I', 42) + reply_body, 'SEND', timestamp=1000))
                if not ack_first:
                    store.apply(self.ack(timestamp=1001))
                store.apply(self.cutin(timestamp=1001.1))
                item = store.sessions[0]
                self.assertEqual(store.issue_count, 0)
                self.assertEqual(len(store.sessions), 1)
                self.assertEqual(len(item.late_replies), 1)
                self.assertEqual(item.late_replies[0]['prompt_step_index'], 1)
                self.assertEqual(item.late_replies[0]['server_acceptance'], 'not_verified')
                self.assertNotIn('reply', item.steps[1])
                self.assertEqual(item.status, 'closed')
                code = AurigaRenderer().render(item)
                self.assertIn('遅延応答候補 1件', code)
                self.assertNotIn('close2;', code)
                self.assertFalse(store.after_close)

    def test_late_reply_scope_resets_and_capacity_do_not_swallow_unrelated_input(self):
        for reset in ('map', 'open', 'capture', 'other-flow', 'other-actor', 'capacity'):
            store = DialogueStore()
            for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                          packet(0xb5, struct.pack('<I', 42)), packet(0xb6, struct.pack('<I', 42))):
                store.apply(event)
            original = store.sessions[0]
            if reset == 'map':
                store.apply(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
            elif reset == 'open':
                store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
            elif reset == 'capture':
                store.begin_capture(1)
            elif reset == 'capacity':
                store.late_reply_count = 10000
            store.apply(packet(0xb9, struct.pack('<I', 43 if reset == 'other-actor' else 42), 'SEND',
                               flow='other' if reset == 'other-flow' else 'flow'), session=1 if reset == 'capture' else 0)
            self.assertFalse(original.late_replies)
            self.assertEqual(store.late_reply_dropped, int(reset == 'capacity'))
            self.assertFalse(store.after_close)

    def test_unanswered_prompts_close_with_timeout_note_independent_of_elapsed_time(self):
        for pid, suffix in ((0xb5, b''), (0xb7, b'one:two:\0'), (0x142, b''), (0x1d4, b'')):
            for when in (1.001, 31, 61):
                store = DialogueStore()
                for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                              packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                              packet(pid, struct.pack('<I', 42) + suffix),
                              packet(0xb6, struct.pack('<I', 42), timestamp=when),
                              packet(0x146, struct.pack('<I', 42), 'SEND', timestamp=when + .1),
                              self.cutin(timestamp=when + .2),
                              packet(0x2b4, struct.pack('<I', 12345), timestamp=when + .3)):
                    store.apply(event)
                item = store.sessions[0]
                self.assertTrue(item.steps[3]['timeout_suspected'])
                self.assertFalse(store.after_close)
                self.assertFalse(item.resource_observations)
                code = AurigaRenderer().render(item)
                self.assertIn('タイムアウト疑い', code)
                self.assertIn('close;', code)
                self.assertNotIn('close2;', code)
                self.assertNotIn('cutin ', code)
                self.assertNotIn('\ndelquest ', code)

    def test_repeated_close_is_terminal_but_new_normal_dialogue_can_still_continue_after_ack(self):
        store = self.start()
        store.apply(packet(0xb6, struct.pack('<I', 42), timestamp=61))
        store.apply(self.ack(timestamp=61.1))
        store.apply(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20), timestamp=61.2))
        item = store.sessions[0]
        self.assertEqual(len(store.sessions), 1)
        self.assertEqual(store.issue_count, 0)
        code = AurigaRenderer().render(item)
        self.assertIn('タイムアウト疑い', code)
        self.assertNotIn('close2;', code)
        self.assertNotIn('warp ', code)
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=62),
                      packet(0xb4, struct.pack('<I', 42) + b'new\0', timestamp=62),
                      packet(0xb6, struct.pack('<I', 42), timestamp=62),
                      self.ack(timestamp=62.1), self.cutin(timestamp=62.2)):
            store.apply(event)
        self.assertIn('close2;', AurigaRenderer().render(store.sessions[1]))

    def cancelled(self):
        store = DialogueStore()
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0xb7, struct.pack('<I', 42) + b'one:two:\0'),
                      packet(0xb8, struct.pack('<IB', 42, 255), 'SEND')):
            store.apply(event)
        return store

    def test_cancel_confirmation_does_not_swallow_subsequent_dialogue_and_next_reply(self):
        store = self.cancelled()
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        cancelled = store.sessions[0]
        self.assertEqual(len(store.sessions), 1)
        self.assertEqual(cancelled.status, 'cancelled')
        self.assertTrue(cancelled.steps[-1]['after_menu_cancel'])
        self.assertFalse(store.close_pending)
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'new observation\0'))
        store.apply(packet(0xb5, struct.pack('<I', 42)))
        store.apply(packet(0xb9, struct.pack('<I', 42), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        self.assertEqual(len(store.sessions), 2)
        item = store.sessions[1]
        self.assertFalse(item.observed_open)
        self.assertEqual(item.steps[2]['reply_to'], 1)
        self.assertIn('mes "new observation";', AurigaRenderer().render(item))
        self.assertNotIn('close2;', AurigaRenderer().render(item))
        self.assertEqual(store.issue_count, 0)

    def test_cancel_confirmation_never_crosses_actor_flow_capture_or_expiry(self):
        for actor, kwargs, session in ((99, {}, 0), (42, {'flow': 'other'}, 0),
                                       (42, {}, 1), (42, {'timestamp': 4}, 0)):
            with self.subTest(actor=actor, kwargs=kwargs, session=session):
                store = self.cancelled()
                store.apply(packet(0xb6, struct.pack('<I', actor), **kwargs), session=session)
                self.assertEqual(len(store.sessions), 2)
                self.assertNotIn('after_menu_cancel', store.sessions[-1].steps[-1])
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb8, struct.pack('<IB', 42, 255), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        self.assertEqual(len(store.sessions), 2)

    def start(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        return store

    def cutin(self, **kwargs):
        return packet(0x1b3, b'portrait.bmp'.ljust(64, b'\0') + b'\x02', **kwargs)

    def ack(self, **kwargs):
        return packet(0x146, struct.pack('<I', 42), 'SEND', **kwargs)

    def test_before_reply_events_are_separate_and_close_is_terminal(self):
        store = self.start()
        store.apply(self.cutin())
        store.apply(packet(0xc0, struct.pack('<IB', 42, 3)))
        store.apply(self.ack())
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('close;', code)
        self.assertNotIn('close2;', code)
        self.assertNotIn('cutin ', code)
        self.assertNotIn('end;', code)
        self.assertEqual([row['context'] for row in store.presentation_observations],
                         ['close_wait', 'close_wait'])

    def test_reply_then_cutin_warp_cutin_keeps_order_and_final_end(self):
        store = self.start()
        store.apply(self.ack())
        store.apply(self.cutin())
        store.apply(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
        store.apply(packet(0x1b3, bytes(64) + b'\xff'))
        self.assertEqual(len(store.sessions), 1)
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('close2;', code)
        self.assertIn('warp "test.gat",10,20;', code)
        self.assertEqual(code.count('end;'), 1)
        self.assertLess(code.index('close2;'), code.index('cutin '))
        self.assertLess(code.index('warp '), code.rindex('cutin '))
        self.assertLess(code.rindex('cutin '), code.index('end;'))

    def test_reply_alone_or_unrelated_followup_does_not_imply_close2(self):
        for changes in ({'flow': 'other'}, {'timestamp': 4}):
            with self.subTest(changes=changes):
                store = self.start()
                store.apply(self.ack())
                store.apply(self.cutin(**changes))
                self.assertNotIn('close2;', AurigaRenderer().render(store.sessions[0]))

    def test_reply_then_message_then_close_finishes_without_extra_end(self):
        store = self.start()
        store.apply(self.ack())
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'continued\0'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('close2;', code)
        self.assertIn('mes "continued";', code)
        self.assertTrue(code.rstrip().endswith('close;'))
        self.assertNotIn('end;', code)

    def test_message_between_reply_and_warp_preserves_warp(self):
        store = self.start()
        store.apply(self.ack())
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'continued\0'))
        store.apply(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
        store.apply(self.cutin())
        item = store.sessions[0]
        code = AurigaRenderer().render(item)
        self.assertIn('close2;', code)
        self.assertLess(code.index('mes "continued";'), code.index('warp '))
        self.assertIn('cutin ', code)
        self.assertLess(code.index('warp '), code.index('cutin '))
        self.assertEqual(code.count('end;'), 1)
        self.assertFalse(store.active)

    def test_pending_input_does_not_turn_external_warp_into_continuation(self):
        store = self.start()
        store.apply(self.ack())
        store.apply(packet(0x142, struct.pack('<I', 42)))
        store.apply(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('close2;', code)
        self.assertNotIn('warp ', code)
        self.assertEqual(store.sessions[0].status, 'map_changed')

    def test_other_operation_and_capture_change_clear_recent_close(self):
        for new_capture in (False, True):
            with self.subTest(new_capture=new_capture):
                store = self.start()
                store.apply(self.ack())
                if new_capture:
                    store.apply(self.cutin(), session=1)
                else:
                    store.apply(packet(0x85, bytes(3), 'SEND'))
                    store.apply(self.cutin())
                self.assertNotIn('close2;', AurigaRenderer().render(store.sessions[0]))

    def test_messages_and_warp_do_not_extend_ack_attribution_window(self):
        store = self.start()
        store.apply(self.ack(timestamp=1))
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'continued\0', timestamp=2))
        store.apply(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20), timestamp=2.9))
        store.apply(self.cutin(timestamp=3.1))
        code = AurigaRenderer().render(store.sessions[0])
        self.assertIn('warp ', code)
        self.assertNotIn('cutin ', code)

    def test_malformed_followup_stops_context_without_raising(self):
        store = self.start()
        store.apply(self.ack())
        store.apply(packet(0x1b3, b'broken'))
        self.assertEqual(store.sessions[0].status, 'decode_error')
        self.assertEqual(store.issue_count, 1)
        self.assertFalse(store.after_close)
        store.apply(self.cutin())
        self.assertNotIn('cutin ', AurigaRenderer().render(store.sessions[0]))

    def test_merged_close_variants_preserve_evidence_and_separate_paths(self):
        plain, continued = self.start(), self.start()
        continued.apply(self.ack())
        continued.apply(self.cutin())
        items = [plain.sessions[0], continued.sessions[0]]
        for item in items:
            item.npc = dict(NPC)
        before = deepcopy([item.steps for item in items])
        report = build_merged(zip(('plain', 'continued'), items))
        self.assertEqual(len(report['groups']), 1)
        code = AurigaRenderer().render_merged(report['groups'][0])
        self.assertIn('close;', code)
        self.assertIn('close2;', code)
        self.assertIn('cutin ', code)
        self.assertIn('end;', code)
        self.assertEqual([item.steps for item in items], before)
