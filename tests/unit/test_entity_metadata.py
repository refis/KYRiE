import struct
import unittest
from copy import deepcopy
from pathlib import Path
from dataclasses import asdict

from parser.display import ReceiveDisplay, DisplayProfile, DEFAULT_PROFILE
from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.entity_metadata import render_npc_initialization
from tests.support.world import actor_packet, name_packet, map_packet
from tests.support.dialogue import packet


class EntityMetadataTests(unittest.TestCase):
    def test_metadata_only_file_requires_observed_placement_and_does_not_invent_dialogue(self):
        world = WorldStore()
        for event in (map_packet(), actor_packet(), name_packet(name='案内人', title='案内役', group_id=9)):
            world.apply(event)
        entity = asdict(world.records('NPC')[0])
        renderer = AurigaRenderer()
        text = renderer.render_npc_metadata_file(entity)
        self.assertIn('script', text)
        self.assertIn('会話本文・起因条件は含みません', text)
        self.assertEqual(text.count('OnInit:'), 1)
        self.assertIn('setnpcgroup 9;', text)
        self.assertNotIn('\n    mes ', text)
        self.assertNotIn('OnTouch', text)
        for changes in ({'map_name': None}, {'class_id': None}, {'metadata_evidence': {}}, {'kind': 'MOB'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                renderer.render_npc_metadata_file(dict(entity, **changes))

    def conversation(self, title='案内', group=7):
        world = WorldStore()
        dialogues = DialogueStore(world=world)
        events = [map_packet(), actor_packet(),
                  packet(0x90, struct.pack('<IB', 42, 1), 'SEND', flow='flow-a', connection='flow-a'),
                  packet(0xb4, struct.pack('<I', 42) + b'hello\0', flow='flow-a', connection='flow-a'),
                  packet(0xb6, struct.pack('<I', 42), flow='flow-a', connection='flow-a'),
                  name_packet(name='案内人', title=title, group_id=group)]
        for index, event in enumerate(events):
            world.apply(event, packet_index=index)
            dialogues.apply(event, packet_index=index)
        self.last_dialogues = dialogues
        return dialogues.sessions[0], world

    def test_npc_initialization_in_body_file_and_merged_output_preserves_observation(self):
        item, world = self.conversation(title='称号"\n表示')
        dialogues = self.last_dialogues
        renderer = AurigaRenderer()
        for text in (renderer.render(item), renderer.render_npc_file(item)):
            self.assertEqual(text.count('OnInit:'), 1)
            self.assertIn('setnpcgroup 7;', text)
            self.assertIn('setnpctitle "称号\\"\\n表示";', text)
            self.assertLess(text.index('close;'), text.index('OnInit:'))
        self.assertEqual(item.npc['metadata_evidence']['group_id']['packet_index'], 5)
        other, _ = self.conversation(title='別の称号')
        group = build_merged([('a', item), ('b', other)])['groups'][0]
        text = renderer.render_merged(group)
        self.assertEqual(text.count('OnInit:'), 1)
        self.assertIn('観測が不一致', text)
        self.assertIn('別の称号', text)
        self.assertEqual(world.issue_count, 0)
        original_metadata = deepcopy(item.npc)
        from tests.support.world import packet as world_packet
        for index, event in enumerate((world_packet(0x80, struct.pack('<IB', 42, 0), timestamp=3),
                                      actor_packet(timestamp=4), name_packet(title='別の出現', timestamp=5)), 10):
            world.apply(event, packet_index=index)
            dialogues.apply(event, packet_index=index)
        self.assertEqual(item.npc, original_metadata)

    def test_zero_and_empty_are_observed_but_unknown_or_invalid_fields_are_not_generated(self):
        item, world = self.conversation(title='', group=0)
        text = AurigaRenderer().render(item)
        self.assertNotIn('setnpcgroup', text)
        self.assertNotIn('setnpctitle', text)
        self.assertNotIn('OnInit:', text)
        for title in ('', '   ', '\t\r\n', '\u3000'):
            item.npc.update(group_id=0, title=title)
            self.assertNotIn('OnInit:', AurigaRenderer().render(item))
        self.assertEqual(item.npc['group_id'], 0)
        item.npc.update(group_id=-1, title='  ')
        self.assertNotIn('OnInit:', AurigaRenderer().render(item))
        item.npc.update(group_id=0, title='表示する称号')
        titled = AurigaRenderer().render(item)
        self.assertIn('setnpctitle "表示する称号";', titled)
        self.assertNotIn('setnpcgroup', titled)
        item.npc.update(group_id=9, title='  ')
        grouped = AurigaRenderer().render(item)
        self.assertIn('setnpcgroup 9;', grouped)
        self.assertNotIn('setnpctitle', grouped)
        self.assertEqual(render_npc_initialization([{'group_id': 0, 'title': ''}]), '')
        compatible = render_npc_initialization([
            {'group_id': 7, 'metadata_evidence': {'group_id': {}}},
            {'title': '観測済み', 'metadata_evidence': {'title': {}}}])
        self.assertIn('setnpcgroup 7;', compatible)
        self.assertIn('setnpctitle "観測済み";', compatible)
        self.assertNotIn('不一致', compatible)
        event = name_packet(title='ok')
        from dataclasses import replace
        world.apply(replace(event, raw=event.raw[:34] + b'\x81\0'))
        entity = world.records('NPC')[0]
        values = dict(group_id=entity.group_id, title=entity.title, metadata_evidence=entity.metadata_evidence,
                      field_issues=entity.field_issues)
        self.assertNotIn('setnpctitle', render_npc_initialization([values]))
        self.assertIn('setnpcgroup 7;', render_npc_initialization([values]))

    def test_deferred_mob_metadata_is_logged_on_appearance_and_cannot_leak_to_reused_actor(self):
        display = ReceiveDisplay(DisplayProfile.load(DEFAULT_PROFILE))
        first = display.decode(name_packet(actor_id=43, title='BOSS'))
        self.assertNotIn('setunitgroup', first.text)
        resolved = display.decode(actor_packet(actor_id=43, actor_type=5, timestamp=3))
        self.assertIn('setunitgroup 7,43;', resolved.text)
        self.assertIn('setunittitle "BOSS",43;', resolved.text)
        self.assertNotIn('OnInit:', resolved.text)
        from tests.support.world import packet as world_packet
        display.decode(world_packet(0x80, struct.pack('<IB', 43, 0), timestamp=4))
        reused = display.decode(actor_packet(actor_id=43, actor_type=5, timestamp=5))
        self.assertNotIn('setunitgroup', reused.text)
        self.assertNotIn('setunittitle', reused.text)
        rathena = ReceiveDisplay(DisplayProfile.load(Path(DEFAULT_PROFILE).parent.parent / 'rathena' / 'display.json'))
        rathena.decode(actor_packet())
        self.assertNotIn('OnInit:', rathena.decode(name_packet()).text)
