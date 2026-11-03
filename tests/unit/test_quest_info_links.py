from copy import deepcopy
import struct
import unittest
from pathlib import Path

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged, conversation_path
from reconstruction.quest_info import collect_quest_info_links, quest_flow_rows, render_quest_info
from reconstruction.quests import ADD_LENGTHS
from tests.support.world import map_packet, actor_packet
from tests.support.dialogue import packet
from tests.support.branches import NPC


def addition(quest_id=12345, timestamp=1.0):
    body = struct.pack('<IBIIH', quest_id, 1, 0, 999, 2) + bytes(ADD_LENGTHS[0xb0c] - 17)
    return packet(0xb0c, body, timestamp=timestamp, connection='flow-a', flow='')


def marker(actor=42, x=10, y=20, state=1, kind=2, timestamp=1.0):
    return packet(0x446, struct.pack('<IHHHH', actor, x, y, state, kind),
                  timestamp=timestamp, connection='flow-a', flow='')


def talk(pid, data=b'', direction='RECV', timestamp=1.0):
    return packet(pid, data, direction, timestamp=timestamp, connection='flow-a', flow='')


class QuestInfoLinkTests(unittest.TestCase):
    def _talk_then(self, events, *, actor=42, name='レイジー#ep20_end01'):
        world = WorldStore()
        store = DialogueStore(world=world)
        sequence = [map_packet(), actor_packet(actor_id=actor, name=name),
                    talk(0x90, struct.pack('<IB', actor, 1), 'SEND'),
                    talk(0xb4, struct.pack('<I', actor) + b'hello\0')]
        sequence.extend(events)
        for event in sequence:
            world.apply(event)
            store.apply(event)
        item = store.sessions[0]
        if not item.npc.get('name'):
            item.npc = dict(NPC, name=name, actor_id=actor)
        return item

    def test_setquest_then_showevent_emits_onquestinfo_with_quest_comment(self):
        item = self._talk_then([
            addition(12345),
            marker(42, 368, 222, 0, 1),
            talk(0xb6, struct.pack('<I', 42)),
        ])
        self.assertEqual(len(item.quest_info_links), 1)
        link = item.quest_info_links[0]
        self.assertEqual(link['quest_id'], 12345)
        self.assertEqual(link['quest_kind'], 'quest_add')
        self.assertEqual((link['state'], link['kind'], link['x'], link['y']), (0, 1, 368, 222))
        self.assertEqual(link['target_name'], 'レイジー#ep20_end01')
        before = deepcopy(item)
        code = AurigaRenderer().render(item)
        self.assertIn('setquest 12345;', code)
        self.assertIn('OnQuestInfo:', code)
        self.assertIn('showevent 0, 1, "レイジー#ep20_end01";', code)
        self.assertIn('// 12345: 368, 222', code)
        self.assertLess(code.index('setquest 12345;'), code.index('OnQuestInfo:'))
        self.assertIn('end;', code.split('OnQuestInfo:', 1)[1])
        self.assertFalse(any(line.strip().startswith('// イベントアイコン') for line in code.splitlines()))
        body, _, quest = code.partition('OnQuestInfo:')
        self.assertNotIn('showevent', body)
        self.assertIn('showevent', quest)
        self.assertEqual(item, before)
        tokens = conversation_path('', item, strict=False)
        self.assertFalse(any(token['kind'] == 'event_marker' for token in tokens))

    def test_after_close_delquest_then_showevent_associates(self):
        world = WorldStore()
        store = DialogueStore(world=world)
        for event in (
                map_packet(), actor_packet(name='案内人'),
                talk(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                talk(0xb4, struct.pack('<I', 42) + b'bye\0'),
                talk(0xb6, struct.pack('<I', 42)),
                talk(0x146, struct.pack('<I', 42), 'SEND', timestamp=2.0),
                talk(0x2b4, struct.pack('<I', 3593), timestamp=2.5),
                marker(42, 10, 20, 2, 3, timestamp=3.0)):
            world.apply(event)
            store.apply(event)
        item = store.sessions[0]
        if not item.npc.get('name'):
            item.npc = dict(NPC)
        self.assertEqual(len(item.quest_info_links), 1)
        self.assertEqual(item.quest_info_links[0]['quest_kind'], 'quest_delete')
        self.assertEqual(item.quest_info_links[0]['quest_id'], 3593)
        self.assertTrue(item.quest_info_links[0]['after_close_reply'])
        code = AurigaRenderer().render(item)
        self.assertIn('close2;', code)
        self.assertIn('delquest 3593;', code)
        self.assertIn('OnQuestInfo:', code)
        self.assertIn('showevent 2, 3, "案内人";', code)
        self.assertIn('// 3593: 10, 20', code)

    def test_unassociated_event_marker_stays_comment_only(self):
        item = self._talk_then([
            marker(42, 1, 2, 3, 4),
            talk(0xb6, struct.pack('<I', 42)),
        ])
        self.assertFalse(item.quest_info_links)
        code = AurigaRenderer().render(item)
        self.assertNotIn('OnQuestInfo:', code)
        self.assertFalse(any(line.strip().startswith('showevent') for line in code.splitlines()))
        self.assertTrue(any('イベントアイコン' in line for line in code.splitlines()))

    def test_external_marker_after_setquest_uses_target_name(self):
        item = self._talk_then([
            actor_packet(actor_id=43, name='看板#mark'),
            addition(12345),
            marker(43, 5, 6, 1, 0),
            talk(0xb6, struct.pack('<I', 42)),
        ], name='話者')
        self.assertEqual(len(item.quest_info_links), 1)
        self.assertEqual(item.quest_info_links[0]['target_name'], '看板#mark')
        self.assertEqual(len(item.external_presentations), 1)
        self.assertTrue(item.external_presentations[0].get('quest_info_linked'))
        code = AurigaRenderer().render(item)
        self.assertIn('showevent 1, 0, "看板#mark";', code)
        self.assertIn('// 12345: 5, 6', code)
        self.assertFalse(any('イベントアイコンの外部候補' in line for line in code.splitlines()))

    def test_collect_and_merge_keep_chronological_unique_links(self):
        first = self._talk_then([
            addition(12345), marker(42, 1, 1, 0, 1), talk(0xb6, struct.pack('<I', 42)),
        ])
        second = deepcopy(first)
        second.id = 2
        second.quest_info_links[0] = dict(
            second.quest_info_links[0], quest_id=999, quest_packet_index=100,
            marker_packet_index=101, quest_timestamp=10.0, marker_timestamp=11.0)
        rows = collect_quest_info_links(first, second, first)
        self.assertEqual([row['quest_id'] for row in rows], [12345, 999])
        group = build_merged([('one', first)])['groups'][0]
        code = AurigaRenderer().render_merged(group)
        self.assertIn('OnQuestInfo:', code)
        self.assertIn('showevent 0, 1, "レイジー#ep20_end01";', code)

    def test_rathena_profile_keeps_showevent_commented(self):
        item = self._talk_then([
            addition(12345), marker(42, 8, 9, 0, 1), talk(0xb6, struct.pack('<I', 42)),
        ])
        code = AurigaRenderer(Path('config/rathena/dialogue.json')).render(item)
        self.assertIn('OnQuestInfo:', code)
        self.assertTrue(any(line.strip().startswith('// showevent 0, 1,') for line in code.splitlines()))
        self.assertFalse(any(line.strip().startswith('showevent ') for line in code.splitlines()))

    def test_render_quest_info_rejects_bad_label(self):
        with self.assertRaises(ValueError):
            render_quest_info(
                [dict(quest_id=1, state=0, kind=1, x=1, y=2, target_name='A')],
                dict(onquestinfo='OnInit:', showevent_quest='x', end='end;', indent='\t'))

    def test_quest_flow_rows_include_unlinked_then_linked_in_order(self):
        item = self._talk_then([
            addition(100),
            addition(200),
            marker(42, 1, 2, 0, 1),
            talk(0xb6, struct.pack('<I', 42)),
        ])
        # Latest unmatched quest (200) consumes the showevent; 100 stays unlinked.
        self.assertEqual(len(item.quest_info_links), 1)
        self.assertEqual(item.quest_info_links[0]['quest_id'], 200)
        rows = quest_flow_rows(item)
        self.assertEqual([row['quest_id'] for row in rows], [100, 200])
        self.assertFalse(rows[0]['linked'])
        self.assertTrue(rows[1]['linked'])
        self.assertEqual((rows[1]['state'], rows[1]['kind'], rows[1]['x'], rows[1]['y']), (0, 1, 1, 2))


if __name__ == '__main__':
    unittest.main()
