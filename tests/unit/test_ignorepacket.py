from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from parser.ignorepacket import (IgnorePacket, observation_tags, packet_ids, packet_flag_entries,
                                 HIDE_LOG, SKIP_SAVE)
from reconstruction.world import WorldStore
from tests.support.dialogue import packet
from tests.support.skills import mob, damage
from tests.support.world import actor_packet, map_packet


class IgnorePacketTests(unittest.TestCase):
    def test_missing_file_loads_defaults_and_ensure_seeds_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ignorepacket.json'
            self.assertEqual(IgnorePacket.load(path), IgnorePacket())
            self.assertTrue(IgnorePacket.ensure_default_file(path))
            self.assertTrue(path.is_file())
            seeded = IgnorePacket.load(path)
            self.assertEqual(seeded, IgnorePacket())
            customized = IgnorePacket(frozenset({0xb0}), frozenset(), True, frozenset(), frozenset())
            customized.save(path)
            self.assertFalse(IgnorePacket.ensure_default_file(path))
            self.assertEqual(IgnorePacket.load(path), customized)

    def test_failed_atomic_save_keeps_original_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ignorepacket.json'
            original = IgnorePacket(frozenset({0x7e}))
            original.save(path)
            with patch('parser.ignorepacket.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    IgnorePacket(mob_combat=True).save(path)
            self.assertEqual(IgnorePacket.load(path), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_ids_roundtrip_and_invalid_config(self):
        value = IgnorePacket(packet_ids('0085, 0x007e\n00B4; 85'), frozenset({0x7e}), True,
                             frozenset({42}), frozenset({'案内人'}))
        self.assertEqual(value.ids, {0x85, 0x7e, 0xb4})
        self.assertEqual(value.skip_save, {0x7e})
        self.assertEqual(value.packet_flag(0x7e), HIDE_LOG | SKIP_SAVE)
        self.assertEqual(value.packet_flag(0x85), HIDE_LOG)
        self.assertTrue(value.skips_save(0x7e))
        self.assertFalse(value.skips_save(0x85))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ignorepacket.json'
            value.save(path)
            self.assertEqual(IgnorePacket.load(path), value)
            self.assertFalse(path.with_suffix('.json.tmp').exists())
            doc = value.document()
            self.assertEqual(doc['version'], 2)
            self.assertEqual(doc['packet_flags']['007E'], 3)
            for field, bad in (('mob_combat', 1), ('npc_actor_ids', [True]),
                               ('packet_flags', {'10000': 1}), ('npc_names', [''])):
                with self.subTest(field=field):
                    path.write_text(json.dumps(dict(doc, **{field: bad})), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        IgnorePacket.load(path)
            # Legacy v1 configs still load as log-hide only.
            legacy = dict(version=1, packet_ids=['0085'], mob_combat=False,
                          npc_actor_ids=[], npc_names=[])
            path.write_text(json.dumps(legacy), encoding='utf-8')
            loaded = IgnorePacket.load(path)
            self.assertEqual(loaded.ids, {0x85})
            self.assertEqual(loaded.skip_save, frozenset())
        for bad in ('10000', '-1', '0x', '0085-0087', 'walk'):
            with self.assertRaises(ValueError):
                packet_ids(bad)
        flags = packet_flag_entries('0085:3\n007E:2, 00B4')
        self.assertEqual(flags, {0x85: 3, 0x7e: 2, 0xb4: 1})
        for bad in ('0085:0', '0085:4', '0085:x', '0085:'):
            with self.assertRaises(ValueError):
                packet_flag_entries(bad)

    def test_mob_source_only_and_fail_open_for_unknown_or_malformed(self):
        world = WorldStore()
        world.apply(mob())
        event = damage()
        settings = IgnorePacket(mob_combat=True)
        self.assertTrue(settings.hides(event, observation_tags(event, world, 0)))
        self.assertFalse(settings.hides(damage(actor=99, target=42),
                                       observation_tags(damage(actor=99, target=42), world, 0)))
        malformed = replace(event, raw=b'\xde\x01')
        self.assertFalse(settings.hides(malformed, observation_tags(malformed, world, 0)))
        sent = replace(event, direction='SEND')
        self.assertFalse(settings.hides(sent, observation_tags(sent, world, 0)))

    def test_npc_names_use_observation_time_identity_and_actor_rule_is_scoped_to_presentations(self):
        world = WorldStore()
        world.apply(actor_packet(name='案内人'))
        event = packet(0xc0, struct.pack('<IB', 42, 3), connection='flow-a', flow='')
        tags = observation_tags(event, world, 0)
        named = IgnorePacket(npc_names=frozenset({'案内人'}))
        by_id = IgnorePacket(npc_actors=frozenset({42}))
        self.assertTrue(named.hides(event, tags))
        self.assertTrue(by_id.hides(event, tags))
        world.apply(map_packet())
        world.apply(actor_packet(name='別人'))
        self.assertFalse(named.hides(event, observation_tags(event, world, 0)))
        self.assertTrue(named.hides(event, tags))
        self.assertFalse(by_id.hides(packet(0xb4, struct.pack('<I', 42) + b'text\0'), {}))
        world.apply(map_packet(name='other.gat'))
        world.apply(mob())
        self.assertFalse(by_id.hides(event, observation_tags(event, world, 0)))

    def test_skip_save_does_not_hide_log(self):
        event = packet(0xc0, struct.pack('<IB', 42, 3))
        settings = IgnorePacket(skip_save=frozenset({0xc0}))
        self.assertTrue(settings.skips_save(0xc0))
        self.assertFalse(settings.hides(event, {}))
        settings = IgnorePacket(ids=frozenset({0xc0}), skip_save=frozenset({0xc0}))
        self.assertTrue(settings.hides(event, {}))
        self.assertEqual(settings.packet_flag(0xc0), HIDE_LOG | SKIP_SAVE)
