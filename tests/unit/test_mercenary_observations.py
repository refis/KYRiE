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


def mercenary(actor=42, name=b'Merc', duration=60):
    body = bytearray(78)
    struct.pack_into('<I', body, 0, actor)
    body[20:20 + len(name)] = name
    struct.pack_into('<I', body, 62, duration)
    return packet(0x29b, bytes(body))


class MercenaryObservationTests(unittest.TestCase):
    def test_mercenary_preserves_fields_without_makemerc(self):
        for waiting in (False, True):
            world = WorldStore()
            store = DialogueStore(world=world)
            events = [map_packet(), actor_packet(), actor_packet(actor_id=43, name='Target'),
                      packet(0x90, struct.pack('<IB', 42, 1), direction='SEND')]
            if waiting:
                events.append(packet(0xb5, struct.pack('<I', 42)))
            events.extend([mercenary(42, b'Own', 10), mercenary(43, b'Ext', 20)])
            if waiting:
                events.append(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
            events.append(packet(0xb6, struct.pack('<I', 42)))
            for event in events:
                world.apply(event)
                store.apply(event)
            item = store.sessions[0]
            own = item.parallel_presentations[0] if waiting else item.steps[1]
            self.assertEqual(own['kind'], 'mercenary')
            self.assertEqual(own['fields'], {'name': 'Own', 'duration': 10})
            self.assertEqual(item.external_presentations[0]['fields'],
                             {'name': 'Ext', 'duration': 20})
            code = AurigaRenderer().render(item)
            self.assertIn('name="Ext"', code)
            self.assertIn('target="Target"', code)
            self.assertTrue(any('傭兵表示' in line for line in code.splitlines()))
            self.assertFalse(any('makemerc' in line and not line.lstrip().startswith('//')
                                 for line in code.splitlines()))
            self.assertFalse(build_merged([('one', item)])['excluded'])
        self.assertEqual(decode_dialogue(mercenary()),
                         ('mercenary', 42, {'name': 'Merc', 'duration': 60}))
        good = mercenary()
        self.assertIsNone(decode_dialogue(replace(good, direction='SEND')))
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(good, raw=good.raw[:-1]))

    def test_display_context_preserves_actor_and_never_confirms_cause(self):
        from gui.presentation_context import presentation_context
        row = dict(kind='mercenary', packet_id=0x29b, actor_id=43,
                   context='during_dialogue', npc={'name': 'Target'},
                   fields={'name': 'Ext', 'duration': 20})
        before = deepcopy(row)
        note = presentation_context(row)
        self.assertEqual(note['actor_role'], 'mercenary_actor')
        self.assertEqual(note['observed_actor_id'], 43)
        self.assertFalse(note['cause_confirmed'])
        self.assertFalse(note['automatic_timer_supported'])
        self.assertEqual(row, before)
