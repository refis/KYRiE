import json
import struct
import unittest
from copy import deepcopy
from dataclasses import replace

from parser.display import DisplayProfile,ReceiveDisplay,DEFAULT_PROFILE
from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.npc_bundle import build_npc_bundle
from reconstruction.decoder import decode_world_event
from reconstruction.actor_appearance import player_class
from tests.support.world import actor_packet,map_packet,packet
from tests.support.dialogue import packet as dialogue_packet


def actor(class_id=45,actor_id=42,kind=6,x=150,pid=0x9ff,visual=False):
    event=actor_packet(actor_id=actor_id,actor_type=kind,name='Guide',x=x,pid=pid)
    raw=bytearray(event.raw);struct.pack_into('<H',raw,23,class_id)
    if visual:
        moving=pid==0x9fd
        raw[66 if moving else 62]=1
        for offset,value in ((25,3),(35,23),(41 if moving else 37,21),(43 if moving else 39,22),
                             (45 if moving else 41,7),(47 if moving else 43,9),(51 if moving else 47,24),
                             (88 if moving else 81 if pid==0x9fe else 82,5)):
            struct.pack_into('<H',raw,offset,value)
    return replace(event,raw=bytes(raw))


class ActorAppearanceTests(unittest.TestCase):
    def test_first_observation_duplicate_suppression_and_delta_only_for_npc_and_mob(self):
        for kind,cls in ((6,45),(5,1018)):
            with self.subTest(kind=kind):
                display=ReceiveDisplay(DisplayProfile.load())
                first=display.decode(actor(class_id=cls,kind=kind))
                self.assertIn('初回観測',first.text)
                self.assertEqual(display.decode(actor(class_id=cls,kind=kind),timestamp=True).text,'')
                delta=display.decode(actor(class_id=cls,kind=kind,x=152)).text
                self.assertIn('X: 150 → 152',delta)
                self.assertNotIn('初回観測',delta)
                self.assertNotIn('速度:',delta)
                display.decode(packet(0x80,struct.pack('<IB',42,0)))
                self.assertEqual(display.decode(actor(class_id=cls,kind=kind,x=152)).text,'')

    def test_job_npc_uses_844_and_observed_full_oninit_arguments_for_all_layouts(self):
        self.assertTrue(player_class(4001))
        self.assertFalse(player_class(844))
        for pid in (0x9ff,0x9fe,0x9fd):
            with self.subTest(pid=pid):
                world=WorldStore();world.apply(map_packet('test.gat'))
                if pid==0x9fd:
                    world.apply(actor(4001,visual=True))  # Movement packets do not carry facing.
                world.apply(actor(4001,pid=pid,visual=True))
                npc=world.snapshot('NPC')['entities'][0];before=deepcopy(npc)
                bundle=build_npc_bundle([npc],[])
                code=bundle['auriga']
                self.assertIn('\tscript\tGuide\t844,{',code)
                self.assertIn('OnInit:',code)
                self.assertIn('setnpcdisplay "Guide",4001,1,3,7,9,21,22,23,24,5;',code)
                self.assertEqual(npc['class_id'],4001)
                self.assertEqual(npc['appearance_data'],npc['initial_display']['appearance_data'])
                self.assertEqual(npc,before)

    def test_visible_class_change_without_dialogue_is_native_and_preserves_initial_class(self):
        display=ReceiveDisplay(DisplayProfile.load())
        display.decode(map_packet('test.gat'));display.decode(actor())
        event=packet(0x1b0,struct.pack('<IBI',42,0,139))
        text=display.decode(event).text
        self.assertIn('class: 45 → 139',text)
        self.assertIn('\nsetnpcdisplay "Guide",139;',text)
        entity=display.world.snapshot('NPC')['entities'][0]
        self.assertEqual(entity['class_id'],139)
        bundle=build_npc_bundle([entity],[])
        self.assertIn('\tscript\tGuide\t45,{}',bundle['auriga'])
        self.assertEqual(display.decode(event).text,'')

    def test_out_of_sight_class_change_and_changed_reappearance_have_warning_comments(self):
        for explicit in (False,True):
            display=ReceiveDisplay(DisplayProfile.load())
            display.decode(actor())
            display.decode(packet(0x80,struct.pack('<IB',42,0)))
            event=packet(0x1b0,struct.pack('<IBI',42,0,139)) if explicit else actor(139)
            text=display.decode(event).text
            self.assertIn('// setnpcdisplay "Guide",139;',text)
            self.assertIn('視界外',text)
            self.assertFalse(any(line.startswith('setnpcdisplay ') for line in text.splitlines()))

    def test_other_npc_class_change_is_named_inside_dialogue_without_interrupting_input(self):
        world=WorldStore();store=DialogueStore(world=world)
        def consume(event):
            world.apply(event);store.apply(event)
        consume(map_packet('test.gat'));consume(actor());consume(actor(actor_id=43))
        consume(packet(0x90,struct.pack('<IB',42,1),direction='SEND'))
        consume(packet(0xb5,struct.pack('<I',42)))
        consume(packet(0x1b0,struct.pack('<IBI',43,0,844)))
        consume(packet(0xb9,struct.pack('<I',42),direction='SEND'))
        consume(packet(0xb6,struct.pack('<I',42)))
        item=store.sessions[0]
        self.assertEqual(item.steps[2]['reply_to'],1)
        self.assertIn('setnpcdisplay "Guide",844;',AurigaRenderer().render(item))

    def test_job_appearance_keeps_original_initial_look_after_later_class_changes(self):
        world=WorldStore();world.apply(map_packet('test.gat'));world.apply(actor(4001,visual=True))
        world.apply(packet(0x1b0,struct.pack('<IBI',42,0,139)))
        npc=world.snapshot('NPC')['entities'][0]
        code=build_npc_bundle([npc],[])['auriga']
        self.assertIn('\tscript\tGuide\t844,{',code)
        self.assertIn('setnpcdisplay "Guide",4001,1,3,7,9,21,22,23,24,5;',code)
        self.assertNotIn('setnpcdisplay "Guide",139;',code)

    def test_change_text_is_external_and_capture_reset_restores_first_observation(self):
        document=json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        document['actor_change_labels']['x']='横座標'
        document['actor_change_template']='{actor_kind}/{actor_id}: {changes_text}'
        display=ReceiveDisplay(DisplayProfile(document));display.decode(actor())
        self.assertIn('横座標: 150 → 152',display.decode(actor(x=152)).text)
        display.reset()
        self.assertIn('初回観測',display.decode(actor()).text)

    def test_unreadable_reobservation_name_is_not_silently_hidden(self):
        display=ReceiveDisplay(DisplayProfile.load())
        display.decode(actor())
        event=actor()
        raw=bytearray(event.raw);raw[84:]=b'\x81\x00'
        struct.pack_into('<H',raw,2,len(raw))
        result=display.decode(replace(event,raw=bytes(raw)))
        self.assertTrue(result.text)
        self.assertFalse(result.fields['name_valid'])

    def test_player_style_native_shop_keeps_initialization_as_review_without_invented_helper(self):
        from tests.unit.test_shop_export import observe_shop
        record,item=observe_shop(False)
        record['npc']['class_id']=4001
        item.npc['class_id']=4001
        report=build_npc_bundle([], [item], shops=[record])
        self.assertEqual(report['review_only_count'],1)
        self.assertTrue(all(not line.strip() or line.startswith('//') for line in report['entries'][0]['auriga'].splitlines()))

    def test_player_style_npc_uses_underlying_844_for_touch_inference(self):
        world=WorldStore();store=DialogueStore(world=world)
        def consume(event):
            world.apply(event);store.apply(event)
        consume(map_packet('test.gat'));consume(actor(4001,visual=True))
        consume(dialogue_packet(0xb4,struct.pack('<I',42)+b'hello\0',flow=None,connection='flow-a'))
        consume(packet(0xb6,struct.pack('<I',42)))
        report=build_npc_bundle([],store.sessions,merge=True)
        self.assertIn('844,1,1,{',report['auriga'])
        self.assertIn('OnTouch:',report['auriga'])
        self.assertIn('OnInit:',report['auriga'])

    def test_malformed_class_notice_does_not_mutate_known_appearance(self):
        world=WorldStore();world.apply(actor())
        world.apply(packet(0x1b0,struct.pack('<IBI',42,1,139)+b'extra'))
        self.assertEqual(world.records('NPC')[0].class_id,45)
        self.assertEqual(world.issue_count,1)
        self.assertFalse(world.display_observations)

    def test_spawn_class_changes_are_kept_in_dialogue_with_full_look_and_visibility(self):
        for target in (42,43):
            for pid in (0x9ff,0x9fe,0x9fd):
                for outside in (False,True):
                    with self.subTest(target=target,pid=pid,outside=outside):
                        world=WorldStore();store=DialogueStore(world=world)
                        def consume(event):
                            world.apply(event);store.apply(event)
                        consume(map_packet('test.gat'));consume(actor());consume(actor(actor_id=43))
                        consume(packet(0x90,struct.pack('<IB',42,1),direction='SEND'))
                        consume(packet(0xb5,struct.pack('<I',42)))
                        if outside:
                            consume(packet(0x80,struct.pack('<IB',target,0)))
                        consume(actor(4001,actor_id=target,pid=pid,visual=True))
                        consume(actor(4001,actor_id=target,pid=pid,visual=True))
                        consume(packet(0xb9,struct.pack('<I',42),direction='SEND'))
                        consume(packet(0xb6,struct.pack('<I',42)))
                        item=store.sessions[0]
                        self.assertEqual(len(item.actions),1)
                        self.assertEqual(item.actions[0]['fields']['outside'],outside)
                        self.assertEqual(set(item.actions[0]['fields']['display']),{'class_id','appearance_data'})
                        code=AurigaRenderer().render(item)
                        command='setnpcdisplay "Guide",4001,1,3,7,9,21,22,23,24,5;'
                        self.assertIn(('// ' if outside else '')+command,code)
                        self.assertEqual(item.steps[2]['reply_to'],1)

    def test_dialogue_identity_uses_initial_placement_class_after_display_change(self):
        from reconstruction.branches import build_merged,npc_identity
        from tests.support.branches import conversation
        for initial,current in ((45,139),(4001,139),(4001,4002)):
            for mapped in (False,True):
                with self.subTest(initial=initial,current=current,mapped=mapped):
                    first=conversation(identifier=1);second=conversation(identifier=2)
                    for item,cls in ((first,initial),(second,current)):
                        item.npc['class_id']=cls
                        item.npc['initial_display']={'class_id':initial}
                        if not mapped:
                            item.npc['map_name']=None
                    before=deepcopy(second.npc)
                    self.assertEqual(npc_identity(first),npc_identity(second))
                    report=build_merged([('capture',first),('capture',second)])
                    self.assertEqual(len(report['groups']),1)
                    self.assertFalse(report['excluded'])
                    self.assertEqual(report['groups'][0]['npc']['class_id'],844 if initial==4001 else 45)
                    self.assertEqual(second.npc,before)
                    # Distinct underlying placements still remain separate.
                    second.npc['initial_display']['class_id']=111
                    report=build_merged([('capture',first),('capture',second)])
                    self.assertEqual(len(report['groups']),2)

    def test_merged_job_dialogue_file_keeps_initial_oninit_once_after_class_change(self):
        from reconstruction.branches import build_merged
        world=WorldStore();store=DialogueStore(world=world)
        def consume(event):
            world.apply(event);store.apply(event)
        consume(map_packet('test.gat'));consume(actor(4001,visual=True))
        for cls in (4001,139):
            if cls==139:
                consume(packet(0x1b0,struct.pack('<IBI',42,0,139)))
            consume(packet(0x90,struct.pack('<IB',42,1),direction='SEND'))
            consume(packet(0xb4,struct.pack('<HI',14,42)+b'hello\0'))
            consume(packet(0xb6,struct.pack('<I',42)))
        original=deepcopy(store.sessions)
        report=build_merged([('capture',item) for item in store.sessions])
        self.assertEqual(len(report['groups']),1)
        group=report['groups'][0]
        renderer=AurigaRenderer()
        expected='setnpcdisplay "Guide",4001,1,3,7,9,21,22,23,24,5;'
        for code in (renderer.render_npc_file(store.sessions[0],group),
                     build_npc_bundle(world.snapshot('NPC')['entities'],store.sessions,merge=True)['auriga']):
            self.assertIn('\tscript\tGuide\t844,{',code)
            self.assertEqual(code.count('OnInit:'),1)
            self.assertEqual(code.count(expected),1)
            self.assertNotIn('setnpcdisplay "Guide",139;',code)
        self.assertEqual(store.sessions,original)

    def test_own_class_changes_use_visibility_and_ignore_unchanged_notifications(self):
        for outside in (False,True):
            with self.subTest(outside=outside):
                world=WorldStore();store=DialogueStore(world=world)
                def consume(event):
                    world.apply(event);store.apply(event)
                consume(map_packet('test.gat'));consume(actor())
                consume(packet(0x90,struct.pack('<IB',42,1),direction='SEND'))
                consume(dialogue_packet(0xb4,struct.pack('<I',42)+b'hello\0',flow=None,connection='flow-a'))
                if outside:consume(packet(0x80,struct.pack('<IB',42,0)))
                for cls in (139,139):consume(packet(0x1b0,struct.pack('<IBI',42,0,cls)))
                consume(packet(0xb6,struct.pack('<I',42)))
                code=AurigaRenderer().render(store.sessions[0])
                commands=[line.strip() for line in code.splitlines() if 'setnpcdisplay "Guide",139;' in line]
                self.assertEqual(len(commands),1)
                self.assertEqual(commands[0].startswith('//'),outside)
                self.assertEqual(len(store.sessions[0].actions),1)

    def test_job_contact_survives_class_projection_in_merged_placement_file(self):
        from reconstruction.branches import build_merged
        world=WorldStore();store=DialogueStore(world=world)
        for event in (map_packet('test.gat'),actor(4001,visual=True),
                      dialogue_packet(0xb4,struct.pack('<I',42)+b'touch\0',flow=None,connection='flow-a'),
                      packet(0xb6,struct.pack('<I',42))):
            world.apply(event);store.apply(event)
        item=store.sessions[0]
        group=build_merged([('capture',item)])['groups'][0]
        code=AurigaRenderer().render_npc_file(item,group)
        self.assertIn('OnTouch:',code)
        self.assertIn('844,1,1,',code)
        self.assertEqual(code.count('OnInit:'),1)

    def test_initial_visibility_is_scoped_to_instance_but_shared_across_normal_maps(self):
        for maps,expected in ((('abc1@toy.gat','def1@toy.gat'),0),
                              (('field.gat','town.gat'),2)):
            with self.subTest(maps=maps):
                world=WorldStore()
                for name,options in zip(maps,(2,0)):
                    world.apply(map_packet(name))
                    event=actor();raw=bytearray(event.raw);struct.pack_into('<I',raw,19,options)
                    world.apply(replace(event,raw=bytes(raw)))
                npc=world.records('NPC',active_only=True)[0]
                self.assertEqual(npc.initial_options,expected)
