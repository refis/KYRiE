from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.event_timer_export import build_timer_candidate, validate_timer_candidate
from tests.support.world import packet, map_packet, actor_packet
from tests.support.branches import conversation
from tests.support.event_trials import repeated_report


class EffectRemovalTests(unittest.TestCase):
    def test_removal_has_distinct_own_parallel_and_external_semantics_with_strict_layout(self):
        for waiting in (False, True):
            world = WorldStore()
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([packet(0x19b, struct.pack('<II', 42, 9)),
                           packet(0xb0d, struct.pack('<II', 42, 9)),
                           packet(0xb0d, struct.pack('<II', 43, 9))])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            self.assertEqual(store.issue_count, 0)
            self.assertEqual(item.external_presentations[0]['kind'], 'effect_remove')
            code = AurigaRenderer().render(item)
            self.assertIn('// delmisceffect 9,"Target";', code)
            if waiting:
                self.assertEqual([row['kind'] for row in item.parallel_presentations], ['effect', 'effect_remove'])
                self.assertEqual(item.steps[2]['reply_to'], 1)
            else:
                self.assertIn('\nmisceffect 9;\ndelmisceffect 9;', code)
            self.assertFalse(build_merged([('one', item)])['excluded'])
        good = packet(0xb0d, struct.pack('<II', 42, 9))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        for raw in (good.raw[:-1], good.raw + b'\0'):
            with self.assertRaises(ValueError):
                decode_dialogue(replace(good, raw=raw))

    def test_removal_conflicts_and_manually_confirmed_timer_do_not_become_effect_additions(self):
        for second_kind, value in ((None, None), ('effect_remove', 10), ('effect', 9)):
            first, second = conversation(), conversation(identifier=2)
            step = dict(first.steps[-1], kind='effect_remove', fields={'value': 9})
            first.steps.insert(-1, step)
            if second_kind:
                second.steps.insert(-1, dict(step, kind=second_kind, fields={'value': value}))
            group = build_merged([('one', first), ('two', second)])['groups'][0]
            self.assertEqual(group['presentation_check']['conflicts'], 1)
            self.assertIn('delmisceffect 9;', AurigaRenderer().render_merged(group))
        report = repeated_report('effect_remove')
        before = deepcopy(report)
        with self.assertRaises(ValueError):
            build_timer_candidate(report, 0, [100, 1100])
        saved = build_timer_candidate(report, 0, [100, 1100], confirmed=True)
        self.assertIn('delmisceffect 9;', saved['auriga'])
        self.assertNotIn('\n    misceffect 9;', saved['auriga'])
        self.assertEqual(validate_timer_candidate(saved, report, 0), saved)
        self.assertEqual(report, before)

    def test_display_context_preserves_target_and_never_confirms_cause(self):
        from copy import deepcopy
        from gui.presentation_context import presentation_context
        row = dict(kind='effect_remove', packet_id=2829, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'}, fields={'value': 9})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'effect_target')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertEqual(note['player_context_required'], None)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
