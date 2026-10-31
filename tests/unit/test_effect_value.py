from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.event_timer_export import build_timer_candidate
from tests.support.world import packet, map_packet, actor_packet
from tests.support.branches import conversation
from tests.support.event_trials import repeated_report


class EffectValueTests(unittest.TestCase):
    def test_valued_effect_preserves_both_values_for_own_parallel_external_and_invalid_layouts(self):
        for waiting in (False, True):
            world, store = WorldStore(), None
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([packet(0x284, struct.pack('<III', 42, 333, 0xfffffffe)),
                           packet(0x284, struct.pack('<III', 43, 333, 22))])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            own = item.parallel_presentations[0] if waiting else item.steps[1]
            self.assertEqual(own['fields'], {'effect_id': 333, 'value': 0xfffffffe})
            self.assertEqual(item.external_presentations[0]['fields'], {'effect_id': 333, 'value': 22})
            code = AurigaRenderer().render(item)
            self.assertIn('effect=333, value=22, target="Target"', code)
            self.assertFalse(any(line.strip().startswith(('misceffect ', 'misceffect_value ')) for line in code.splitlines()))
            self.assertFalse(build_merged([('one', item)])['excluded'])
        good = packet(0x284, struct.pack('<III', 42, 333, 9))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        for raw in (good.raw[:-1], good.raw + b'\0'):
            with self.assertRaises(ValueError):
                decode_dialogue(replace(good, raw=raw))

    def test_value_changes_and_presence_conflict_and_unsupported_timer_generation_is_explicit(self):
        for fields in (None, {'effect_id': 333, 'value': 2}, {'effect_id': 334, 'value': 1}):
            first, second = conversation(), conversation(identifier=2)
            first.steps.insert(-1, dict(first.steps[-1], kind='effect_value', fields={'effect_id': 333, 'value': 1}))
            if fields is not None:
                second.steps.insert(-1, dict(second.steps[-1], kind='effect_value', fields=fields))
            before = deepcopy((first, second))
            group = build_merged([('one', first), ('two', second)])['groups'][0]
            self.assertEqual(group['presentation_check']['conflicts'], 1)
            self.assertIn('effect=333, value=1', AurigaRenderer().render_merged(group))
            self.assertEqual((first, second), before)
        report = repeated_report('effect_value')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields'] = {'effect_id': 333, 'value': 9}
        code = build_timer_candidate(report, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('effect=333, value=9', code)
        self.assertTrue(any(line.strip().startswith('//') and '値付きエフェクト' in line
                            for line in code.splitlines()))
        self.assertFalse(any(line.strip().startswith('misceffect ') for line in code.splitlines()))

    def test_display_context_preserves_target_and_never_confirms_cause(self):
        from copy import deepcopy
        from gui.presentation_context import presentation_context
        row = dict(kind='effect_value', packet_id=644, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'}, fields={'value': 9})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'effect_target')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertEqual(note['player_context_required'], None)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
