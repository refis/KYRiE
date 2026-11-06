"""Workspace NPC roster: cross-log review hints without script identity."""
import struct
import unittest
from copy import deepcopy
from dataclasses import replace

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.npc_roster import build_npc_roster, format_roster_candidates, roster_candidates
from reconstruction.auriga import AurigaRenderer
from gui.presentation_context import presentation_context
from tests.support.world import map_packet, actor_packet, packet
from tests.support.dialogue import packet as dialogue_packet


class NpcRosterTests(unittest.TestCase):
    def test_build_and_lookup_other_session_by_actor_id(self):
        world = WorldStore()
        world.apply(map_packet('prontera.gat', connection='flow-a'), packet_index=0)
        # Session 0 names the NPC.
        named = actor_packet(actor_id=99, name='HiddenGuest', connection='flow-a')
        raw = bytearray(named.raw)
        struct.pack_into('<I', raw, 19, 0)
        world.apply(replace(named, raw=bytes(raw)), packet_index=1)
        # Session 1 has no spawn for 99 yet; roster still lists session 0.
        world.apply(map_packet('prontera.gat', connection='flow-b'), session=1, packet_index=0)
        roster = build_npc_roster(world, {0: '/logs/20261103-chapter1/capture.jsonl',
                                          1: '/logs/20261104-chapter1/capture.jsonl'})
        self.assertTrue(any(row['name'] == 'HiddenGuest' and row['actor_id'] == 99 for row in roster))
        matches = roster_candidates(roster, actor_id=99, capture_session=1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['name'], 'HiddenGuest')
        self.assertEqual(matches[0]['match'], 'actor_id')
        self.assertEqual(matches[0]['capture_session'], 0)
        note = format_roster_candidates(matches)
        self.assertIn('HiddenGuest', note)
        self.assertIn('同一視・スクリプト反映はしません', note)
        # Same session is excluded.
        self.assertEqual(roster_candidates(roster, actor_id=99, capture_session=0), [])

    def test_deferred_unobserved_shows_roster_hint_without_script_emit(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        store.source_refs = {0: '/logs/day1/capture.jsonl', 1: '/logs/day2/capture.jsonl'}

        def consume(event, session=0):
            event = replace(event, timestamp=float(store.packet_ordinal + 1))
            world.apply(event, session=session, packet_index=store.packet_ordinal)
            store.apply(event, session=session)

        # Day1: observe NPC 99 by name.
        consume(map_packet('prontera.gat'))
        named = actor_packet(actor_id=99, name='HiddenGuest')
        raw = bytearray(named.raw)
        struct.pack_into('<I', raw, 19, 0)
        consume(replace(named, raw=bytes(raw)))

        # Day2: dialogue owner + unobserved cloakoff for actor 99.
        consume(map_packet('prontera.gat'), session=1)
        consume(packet(0x283, struct.pack('<I', 777)), session=1)
        owner = actor_packet(actor_id=42, name='Owner', connection='flow-a')
        # Use a distinct connection for session 1 packets via default flow-a is ok;
        # capture_session separates entities.
        oraw = bytearray(owner.raw)
        struct.pack_into('<I', oraw, 19, 0)
        consume(replace(owner, raw=bytes(oraw)), session=1)
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'), session=1)
        consume(dialogue_packet(0xb4, struct.pack('<I', 42) + b'hello\0', flow=None, connection='flow-a'),
                session=1)
        consume(packet(0x229, struct.pack('<IHHIB', 99, 0, 0, 0, 0)), session=1)

        pending = [row for row in store.presentation_observations
                   if row.get('fields', {}).get('basis') == 'deferred_unobserved'
                   and row.get('actor_id') == 99]
        self.assertEqual(len(pending), 1)
        roster = build_npc_roster(world, store.source_refs)
        note = presentation_context(pending[0], roster)
        self.assertIn('他ログ候補', note['summary'])
        self.assertEqual(note['workspace_roster_candidates'][0]['name'], 'HiddenGuest')
        before = deepcopy(pending[0])
        presentation_context(pending[0], roster)
        self.assertEqual(pending[0], before)
        # No conversation action name until same-session spawn; renderer stays free of inventing target.
        item = next(item for item in store.sessions if item.capture_session == 1)
        self.assertFalse(any(row['fields'].get('basis') == 'deferred_name_resolved'
                             for row in item.actions))
        code = AurigaRenderer().render(item)
        self.assertNotIn('HiddenGuest', code)


if __name__ == '__main__':
    unittest.main()
