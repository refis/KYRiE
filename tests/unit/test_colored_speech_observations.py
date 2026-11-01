from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.event_timer_export import build_timer_candidate
from reconstruction.decoder import ObservationError
from tests.support.world import packet, map_packet, actor_packet
from tests.support.branches import conversation
from tests.support.event_trials import repeated_report


def colored_speech(actor=42, color=0x00FFAA55, text=b'hello'):
    payload = struct.pack('<II', actor, color) + text + b'\0'
    total = 4 + len(payload)
    return packet(0x2c1, struct.pack('<H', total) + payload)


class ColoredSpeechObservationTests(unittest.TestCase):
    def test_colored_speech_preserves_fields_without_unittalk_command(self):
        for waiting in (False, True):
            world = WorldStore()
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([colored_speech(42, 0x11223344, b'own'),
                           colored_speech(43, 0xAABBCCDD, b'ext')])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            own = item.parallel_presentations[0] if waiting else item.steps[1]
            self.assertEqual(own['kind'], 'colored_speech')
            self.assertEqual(own['fields'], {'color': 0x11223344, 'text': 'own'})
            self.assertEqual(item.external_presentations[0]['fields'],
                             {'color': 0xAABBCCDD, 'text': 'ext'})
            code = AurigaRenderer().render(item)
            self.assertIn('color=0xAABBCCDD', code)
            self.assertIn('target="Target"', code)
            self.assertTrue(any('色付きユニット発言' in line for line in code.splitlines()))
            self.assertFalse(any(line.lstrip().startswith('unittalk')
                                 for line in code.splitlines()))
            self.assertFalse(build_merged([('one', item)])['excluded'])
        good = colored_speech()
        self.assertEqual(decode_dialogue(good),
                         ('colored_speech', 42, {'color': 0x00FFAA55, 'text': 'hello'}))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))

    def test_field_changes_conflict_and_timer_adoption_stays_comment_only(self):
        for fields in (None, {'color': 1, 'text': 'x'}, {'color': 0x00FFAA55, 'text': 'other'}):
            first, second = conversation(), conversation(identifier=2)
            first.steps.insert(-1, dict(first.steps[-1], kind='colored_speech',
                                        fields={'color': 0x00FFAA55, 'text': 'hello'}))
            if fields is not None:
                second.steps.insert(-1, dict(second.steps[-1], kind='colored_speech', fields=fields))
            before = deepcopy((first, second))
            group = build_merged([('one', first), ('two', second)])['groups'][0]
            self.assertEqual(group['presentation_check']['conflicts'], 1)
            self.assertIn('color=0x00FFAA55', AurigaRenderer().render_merged(group))
            self.assertEqual((first, second), before)
        report = repeated_report('colored_speech')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields'] = {'color': 0x00FFAA55, 'text': 'hello'}
        code = build_timer_candidate(report, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('color=0x00FFAA55', code)
        self.assertTrue(any(line.lstrip().startswith('//') and 'color=0x00FFAA55' in line
                            for line in code.splitlines()))
        self.assertFalse(any(line.strip().startswith('unittalk') for line in code.splitlines()))

    def test_display_context_preserves_source_and_never_confirms_cause(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='colored_speech', packet_id=0x2c1, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'},
                   fields={'color': 7, 'text': 'hi'})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'speech_source')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
