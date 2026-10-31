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


def event_marker(actor=42, x=10, y=20, state=1, kind=2):
    return packet(0x446, struct.pack('<IHHHH', actor, x, y, state, kind))


class EventMarkerObservationTests(unittest.TestCase):
    def test_event_marker_preserves_fields_for_own_parallel_external_and_invalid_layouts(self):
        for waiting in (False, True):
            world = WorldStore()
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([event_marker(42, 11, 22, 3, 4), event_marker(43, 30, 40, 5, 6)])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            own = item.parallel_presentations[0] if waiting else item.steps[1]
            self.assertEqual(own['kind'], 'event_marker')
            self.assertEqual(own['fields'], {'x': 11, 'y': 22, 'state': 3, 'kind': 4})
            self.assertEqual(item.external_presentations[0]['fields'],
                             {'x': 30, 'y': 40, 'state': 5, 'kind': 6})
            code = AurigaRenderer().render(item)
            self.assertIn('state=5, kind=6, x=30, y=40, target="Target"', code)
            self.assertTrue(any('イベントアイコン' in line for line in code.splitlines()))
            self.assertFalse(any(line.strip().startswith('showevent') for line in code.splitlines()))
            self.assertFalse(build_merged([('one', item)])['excluded'])
        good = event_marker()
        self.assertEqual(decode_dialogue(good),
                         ('event_marker', 42, {'x': 10, 'y': 20, 'state': 1, 'kind': 2}))
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        for raw in (good.raw[:-1], good.raw + b'\0'):
            with self.assertRaises(ValueError):
                decode_dialogue(replace(good, raw=raw))

    def test_field_changes_conflict_and_timer_adoption_stays_comment_only(self):
        for fields in (None, {'x': 10, 'y': 20, 'state': 1, 'kind': 9},
                       {'x': 11, 'y': 20, 'state': 1, 'kind': 2}):
            first, second = conversation(), conversation(identifier=2)
            first.steps.insert(-1, dict(first.steps[-1], kind='event_marker',
                                        fields={'x': 10, 'y': 20, 'state': 1, 'kind': 2}))
            if fields is not None:
                second.steps.insert(-1, dict(second.steps[-1], kind='event_marker', fields=fields))
            before = deepcopy((first, second))
            group = build_merged([('one', first), ('two', second)])['groups'][0]
            self.assertEqual(group['presentation_check']['conflicts'], 1)
            self.assertIn('state=1, kind=2, x=10, y=20', AurigaRenderer().render_merged(group))
            self.assertEqual((first, second), before)
        report = repeated_report('event_marker')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields'] = {
                'x': 10, 'y': 20, 'state': 1, 'kind': 2}
        code = build_timer_candidate(report, 0, [100, 1100], confirmed=True)['auriga']
        self.assertIn('state=1, kind=2, x=10, y=20', code)
        self.assertFalse(any(line.strip().startswith('showevent') for line in code.splitlines()))

    def test_display_context_preserves_target_and_never_confirms_cause(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='event_marker', packet_id=0x446, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'},
                   fields={'x': 1, 'y': 2, 'state': 3, 'kind': 4})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'event_marker_target')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)

    def test_outside_dialogue_retention_obeys_capacity(self):
        store = DialogueStore()
        store.max_presentations = 1
        store.apply(event_marker(7))
        store.apply(event_marker(8, state=9))
        self.assertEqual(len(store.presentation_observations), 1)
        self.assertEqual(store.presentation_dropped, 1)
        self.assertEqual(store.presentation_observations[0]['actor_id'], 7)
        self.assertFalse(store.sessions)
