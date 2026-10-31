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


def hat_effect(actor=42, enabled=1, effect_id=7):
    body = struct.pack('<HIBH', 11, actor, enabled, effect_id)
    return packet(0xa3b, body)


class HatEffectObservationTests(unittest.TestCase):
    def test_hat_effect_preserves_fields_for_own_parallel_external_and_invalid_layouts(self):
        for waiting in (False, True):
            world = WorldStore()
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([hat_effect(42, 1, 11), hat_effect(43, 0, 22)])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            own = item.parallel_presentations[0] if waiting else item.steps[1]
            self.assertEqual(own['kind'], 'hat_effect')
            self.assertEqual(own['fields'], {'enabled': 1, 'effect_id': 11})
            self.assertEqual(item.external_presentations[0]['fields'],
                             {'enabled': 0, 'effect_id': 22})
            code = AurigaRenderer().render(item)
            self.assertIn('enabled=0, effect=22, target="Target"', code)
            self.assertTrue(any('帽子エフェクト' in line for line in code.splitlines()))
            self.assertFalse(any('hateffect' in line and not line.lstrip().startswith('//')
                                 for line in code.splitlines()))
            self.assertFalse(build_merged([('one', item)])['excluded'])
        good = hat_effect()
        self.assertEqual(decode_dialogue(good),
                         ('hat_effect', 42, {'enabled': 1, 'effect_id': 7}))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        for raw in (good.raw[:-1], good.raw + b'\0',
                    struct.pack('<H', 0xa3b) + struct.pack('<HIBH', 12, 42, 1, 7)):
            with self.assertRaises(ValueError):
                decode_dialogue(replace(good, raw=raw))

    def test_field_changes_conflict_and_timer_adoption_stays_comment_only(self):
        for fields in (None, {'enabled': 1, 'effect_id': 9},
                       {'enabled': 0, 'effect_id': 7}):
            first, second = conversation(), conversation(identifier=2)
            first.steps.insert(-1, dict(first.steps[-1], kind='hat_effect',
                                        fields={'enabled': 1, 'effect_id': 7}))
            if fields is not None:
                second.steps.insert(-1, dict(second.steps[-1], kind='hat_effect', fields=fields))
            before = deepcopy((first, second))
            group = build_merged([('one', first), ('two', second)])['groups'][0]
            self.assertEqual(group['presentation_check']['conflicts'], 1)
            self.assertIn('enabled=1, effect=7', AurigaRenderer().render_merged(group))
            self.assertEqual((first, second), before)
        report = repeated_report('hat_effect')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields'] = {'enabled': 1, 'effect_id': 7}
        code = build_timer_candidate(report, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('enabled=1, effect=7', code)
        self.assertTrue(any(line.lstrip().startswith('//') and 'enabled=1, effect=7' in line
                            for line in code.splitlines()))
        self.assertFalse(any(line.strip().startswith('hateffect') for line in code.splitlines()))

    def test_display_context_preserves_target_and_never_confirms_cause(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='hat_effect', packet_id=0xa3b, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'},
                   fields={'enabled': 1, 'effect_id': 4})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'hat_effect_target')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)

    def test_outside_dialogue_retention_obeys_capacity(self):
        store = DialogueStore()
        store.max_presentations = 1
        store.apply(hat_effect(7))
        store.apply(hat_effect(8, enabled=0, effect_id=9))
        self.assertEqual(len(store.presentation_observations), 1)
        self.assertEqual(store.presentation_dropped, 1)
        self.assertEqual(store.presentation_observations[0]['actor_id'], 7)
        self.assertFalse(store.sessions)
