import struct
import unittest
from dataclasses import replace
from pathlib import Path

from reconstruction.auriga import AurigaRenderer
from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.decoder import ObservationError
from reconstruction.camera import auriga_arguments
from tests.support.dialogue import packet


def camera(show=0, distance=12.34, rotation=-20.5, latitude=30):
    return packet(0xa78, struct.pack('<Bfff', show, distance, rotation, latitude))


class CameraObservationTests(unittest.TestCase):
    def test_decode_and_exact_argument_conversion(self):
        kind, actor, fields = decode_dialogue(camera())
        self.assertEqual(kind, 'camera')
        self.assertIsNone(actor)
        self.assertEqual(auriga_arguments(fields), dict(range=1234, rotation=-2050, latitude=3000))
        for event in (camera(show=1), camera(distance=1.234), camera(distance=1e30)):
            self.assertIsNone(auriga_arguments(decode_dialogue(event)[2]))
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ObservationError):
                decode_dialogue(camera(distance=value))
        with self.assertRaises(ObservationError):
            decode_dialogue(replace(camera(), raw=camera().raw[:-1]))
        self.assertIsNone(decode_dialogue(replace(camera(), direction='SEND')))

    def test_dialogue_generation_and_unassigned_observations(self):
        store = DialogueStore()
        events = [camera(), packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0'), camera(),
                  camera(show=1), camera(distance=1.234),
                  packet(0xb6, struct.pack('<I', 42)), camera()]
        for event in events:
            store.apply(event)
        self.assertEqual([row['context'] for row in store.presentation_observations],
                         ['outside_dialogue', 'close_wait'])
        self.assertTrue(all(row['actor_id'] is None for row in store.presentation_observations))
        item = store.sessions[0]
        self.assertEqual(len(item.actions), 3)
        self.assertTrue(all(row['cause_confirmed'] is False for row in item.actions))
        code = AurigaRenderer().render(item)
        self.assertIn('camerainfo 1234,-2050,3000;', code)
        self.assertEqual(code.count('// Camera observation:'), 2)
        self.assertNotIn('OnTimer', code)
        profile = Path(__file__).resolve().parents[2] / 'config' / 'rathena' / 'dialogue.json'
        other = AurigaRenderer(profile).render(item)
        self.assertFalse(any(line.strip().startswith('camerainfo ') for line in other.splitlines()))

    def test_waiting_input_defers_action_and_invalid_packet_is_reported(self):
        store = DialogueStore()
        for event in [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                      packet(0x142, struct.pack('<I', 42)), camera(),
                      packet(0x143, struct.pack('<Ii', 42, 10), 'SEND'),
                      packet(0xb6, struct.pack('<I', 42))]:
            store.apply(event)
        code = AurigaRenderer().render(store.sessions[0])
        self.assertLess(code.index('input '), code.index('camerainfo '))
        self.assertEqual(store.sessions[0].steps[3]['reply_to'], 2)
        broken = replace(camera(), raw=camera().raw[:-1])
        store.apply(broken)
        self.assertEqual(store.issue_count, 1)

