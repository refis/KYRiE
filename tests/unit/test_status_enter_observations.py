from copy import deepcopy
from dataclasses import replace
import struct
import unittest

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.decoder import ObservationError
from tests.support.world import packet, map_packet, actor_packet


def status_enter(actor=42, effect_id=7, remaining=1000, values=(1, 2, 3), tick=None):
    if tick is None:
        body = struct.pack('<IHIIII', actor, effect_id, remaining, *values)
        return packet(0x8ff, body)
    body = struct.pack('<IHIIIII', actor, effect_id, remaining, tick, *values)
    return packet(0x984, body)


class StatusEnterObservationTests(unittest.TestCase):
    def test_status_enter_preserves_fields_without_sc_start(self):
        for waiting in (False, True):
            world = WorldStore()
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([status_enter(42, 11, 500, (4, 5, 6)),
                           status_enter(43, 22, 700, (7, 8, 9), tick=99)])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            own = item.parallel_presentations[0] if waiting else item.steps[1]
            self.assertEqual(own['kind'], 'status_enter')
            self.assertEqual(own['fields'],
                             {'effect_id': 11, 'remaining_ms': 500,
                              'value1': 4, 'value2': 5, 'value3': 6})
            self.assertEqual(item.external_presentations[0]['fields']['tick'], 99)
            code = AurigaRenderer().render(item)
            self.assertIn('effect=22', code)
            self.assertIn('target="Target"', code)
            self.assertTrue(any('入場時状態' in line for line in code.splitlines()))
            self.assertFalse(any(line.lstrip().startswith('sc_start')
                                 or line.lstrip().startswith('sc_end')
                                 for line in code.splitlines()))
            self.assertFalse(build_merged([('one', item)])['excluded'])
        self.assertEqual(
            decode_dialogue(status_enter()),
            ('status_enter', 42, {'effect_id': 7, 'remaining_ms': 1000,
                                 'value1': 1, 'value2': 2, 'value3': 3}))
        self.assertEqual(
            decode_dialogue(status_enter(tick=3)),
            ('status_enter', 42, {'effect_id': 7, 'remaining_ms': 1000, 'tick': 3,
                                 'value1': 1, 'value2': 2, 'value3': 3}))
        good = status_enter()
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))

    def test_display_context_preserves_target_and_never_confirms_cause(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='status_enter', packet_id=0x8ff, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'},
                   fields={'effect_id': 1, 'remaining_ms': 2, 'value1': 0, 'value2': 0, 'value3': 0})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'status_enter_target')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
