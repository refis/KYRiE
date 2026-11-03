import unittest
from copy import deepcopy
from reconstruction.world import WorldStore
from reconstruction.skills import SkillStore
from reconstruction.combat import CombatStore
from reconstruction.report_snapshot import freeze_mob_report
from tests.support.skills import mob,cast,damage
from tests.support.combat import attack


class ReportSnapshotTests(unittest.TestCase):
    def test_frozen_reports_keep_pending_cast_and_counters_across_later_updates(self):
        world=WorldStore();skills=SkillStore(world);combat=CombatStore(world)
        sources={0:'original.jsonl',1:None};names={177:'観測スキル'}
        def consume(event,index,session=0):
            world.apply(event,session=session,packet_index=index)
            skills.apply(event,session=session,packet_index=index)
            combat.apply(event,session=session,packet_index=index)
        for index,event in enumerate((mob(),attack(),cast(timestamp=2))):consume(event,index)
        skill_expected=dict(deepcopy(skills.snapshot()),source_sessions={'0':'original.jsonl','1':None},skill_names={'177':'観測スキル'})
        combat_expected=dict(deepcopy(combat.snapshot()),source_sessions={'0':'original.jsonl','1':None})
        skill_job=freeze_mob_report(skills,sources,names)
        combat_job=freeze_mob_report(combat,sources)
        consume(damage(timestamp=2.2),3)
        skills.begin_capture(2);combat.begin_capture(2);world.begin_capture(2)
        sources[0]='changed.jsonl';names[177]='変更後'
        skills.issue_count+=1;combat.issue_count+=1
        self.assertEqual(skill_job.build(),skill_expected)
        self.assertEqual(combat_job.build(),combat_expected)
        self.assertNotEqual(skills.snapshot()['observations'],skill_expected['observations'])
        self.assertGreater(combat.snapshot()['issue_count'],combat_expected['issue_count'])

    def test_frozen_spawn_report_survives_later_world_updates(self):
        from reconstruction.mob_spawns import MobSpawnStore
        world = WorldStore()
        spawns = MobSpawnStore(world)
        sources = {0: 'original.jsonl'}
        for index, event in enumerate((mob(),)):
            world.apply(event, packet_index=index)
            spawns.apply(event, packet_index=index)
        expected = dict(deepcopy(spawns.snapshot()), source_sessions={'0': 'original.jsonl'})
        job = freeze_mob_report(spawns, sources)
        world.apply(mob(actor=99), packet_index=1)
        spawns.apply(mob(actor=99), packet_index=1)
        sources[0] = 'changed.jsonl'
        self.assertEqual(job.build(), expected)
        self.assertNotEqual(spawns.snapshot()['groups'], expected['groups'])

    def test_npc_freeze_preserves_dialogue_shops_and_all_rendering_files(self):
        from unittest.mock import patch
        from reconstruction.report_snapshot import freeze_npc_report
        from reconstruction.npc_bundle import build_npc_bundle
        from tests.unit.test_npc_bundle import entity
        from tests.unit.test_shop_export import observe_shop
        from tests.unit.test_barter import observe_barter
        for merge in (False,True):
            direct,opened=observe_shop(False)
            direct['npc']['name']='Direct';opened.npc['name']='Direct'
            opened.id=10;direct['conversation_id']=10
            linked,talk=observe_shop(True)
            barter_record,barter_talk=observe_barter()
            barter_talk.id=20
            barter_record['conversation_id']=20
            barter_talk.npc['name']='BarterNpc'
            entities=[dict(entity(),name='Decorative',actor_id=99)]
            conversations=[opened,talk,barter_talk];shops=[direct,linked];barters=[barter_record]
            sources={0:'original'}
            expected=build_npc_bundle(entities,conversations,sources,merge=merge,shops=shops,barters=barters)
            prepared=freeze_npc_report(entities,conversations,sources,merge=merge,shops=shops,barters=barters)
            entities[0]['title']='changed'
            talk.steps.clear();linked['items'][0]['price']=99999;sources[0]='later'
            barter_record['items'][0]['zeny']=1
            with self.subTest(merge=merge),patch('pathlib.Path.read_bytes',side_effect=AssertionError('late file read')), \
                    patch('pathlib.Path.resolve',side_effect=AssertionError('late path resolution')), \
                    patch('pathlib.Path.open',side_effect=AssertionError('late file open')):
                self.assertEqual(prepared.build(),expected)
                self.assertIn('//-\tbarter\ttest.gat#callbarter', expected['auriga'])

    def test_frozen_rendering_context_is_private_to_its_thread(self):
        from threading import Event,Thread
        from unittest.mock import patch
        from reconstruction.render_inputs import freeze_npc_render_inputs,read_render_json
        from reconstruction.auriga import DEFAULT_DIALOGUE_PROFILE
        frozen=freeze_npc_render_inputs()
        expected=read_render_json(DEFAULT_DIALOGUE_PROFILE)
        entered=Event();release=Event();results=[]
        def worker():
            with frozen.activate():
                entered.set()
                if release.wait(2):results.append(read_render_json(DEFAULT_DIALOGUE_PROFILE))
        thread=Thread(target=worker)
        with patch('pathlib.Path.read_bytes',return_value=b'{"current":"changed"}'):
            try:
                thread.start()
                self.assertTrue(entered.wait(1))
                self.assertEqual(read_render_json(DEFAULT_DIALOGUE_PROFILE),{'current':'changed'})
            finally:
                release.set();thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results,[expected])


    def test_layout_commands_survive_bundle_freeze_and_later_model_profile_changes(self):
        from unittest.mock import patch
        from reconstruction.report_snapshot import freeze_npc_report
        from reconstruction.npc_bundle import build_npc_bundle
        from tests.support.dialogue import layout_conversation
        for merge in (False,True):
            with self.subTest(merge=merge):
                conversations=[layout_conversation(),layout_conversation(320,2,2)]
                sources={0:'original.jsonl'}
                expected=build_npc_bundle([],conversations,sources,merge=merge)
                self.assertFalse(expected['excluded'])
                for command in ('messize 180,280;','messize 180,320;','mespos 10,20;',
                                'mesalign 1;','mesalign 2;'):
                    self.assertIn(command,expected['auriga'])
                prepared=freeze_npc_report([],conversations,sources,merge=merge)
                self.assertEqual(prepared.build(),expected)
                conversations[0].actions[0]['fields']['width']=999
                conversations[1].actions.clear()
                sources[0]='later.jsonl'
                with patch('pathlib.Path.read_bytes',side_effect=AssertionError('late profile read')), \
                     patch('pathlib.Path.open',side_effect=AssertionError('late profile open')):
                    frozen=prepared.build()
                self.assertEqual(frozen,expected)
                self.assertNotIn('messize 180,999;',frozen['auriga'])
