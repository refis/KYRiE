import struct
import unittest

from reconstruction.dialogue import DialogueStore
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from tests.support.dialogue import packet, overhead_event
from tests.support.branches import NPC


class OverheadTests(unittest.TestCase):
    def opened(self):
        store = DialogueStore()
        store.apply(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        store.apply(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        return store

    def test_overhead_is_escaped_distinct_from_mes_and_repeat_differences_are_retained(self):
        trials = []
        for text in ('one', 'two";\nend;'):
            store = self.opened()
            store.apply(overhead_event(text=text))
            store.apply(packet(0xb6, struct.pack('<I', 42)))
            item = store.sessions[0]
            item.npc = dict(NPC)
            self.assertEqual(item.steps[2]['kind'], 'overhead')
            self.assertEqual(item.steps[2]['fields']['text'], text)
            trials.append((text, item))
        code = AurigaRenderer().render(trials[1][1])
        self.assertEqual(sum(row.startswith('showmessage ') for row in code.splitlines()), 1)
        self.assertIn('\\n', code)
        self.assertNotIn('\nend;', code)
        self.assertEqual(build_merged(trials)['groups'][0]['presentation_check']['conflicts'], 1)

    def test_input_wait_other_actor_and_close_reply_use_actor_at_offset_four(self):
        store = self.opened()
        store.apply(packet(0x142, struct.pack('<I', 42)))
        store.apply(overhead_event())
        store.apply(overhead_event(actor=99))
        store.apply(packet(0x143, struct.pack('<Ii', 42, 7), 'SEND'))
        store.apply(packet(0xb6, struct.pack('<I', 42)))
        store.apply(overhead_event(text='before close reply'))
        store.apply(packet(0x146, struct.pack('<I', 42), 'SEND'))
        store.apply(overhead_event(text='after close reply'))
        item = store.sessions[0]
        self.assertEqual(item.steps[3]['reply_to'], 2)
        self.assertEqual([row['context'] for row in store.presentation_observations],
                         ['input_wait', 'outside_dialogue', 'close_wait'])
        code = AurigaRenderer().render(item)
        self.assertIn('close2;', code)
        self.assertIn('showmessage "after close reply";', code)
        self.assertNotIn('showmessage "before close reply";', code)

    def test_malformed_or_invalid_cp932_is_reported_without_payload(self):
        invalid = packet(0x8b3, struct.pack('<HI', 10, 42) + b'\x81\0')
        for event in (packet(0x8b3, b'private'), invalid):
            with self.subTest(length=len(event.raw)):
                store = self.opened()
                store.apply(event)
                self.assertEqual(store.issue_count, 1)
                self.assertFalse(store.presentation_observations)
                self.assertNotIn('private', str(store.issues))

    def test_self_player_notifications_link_context_without_becoming_npc_commands(self):
        from dataclasses import replace
        from reconstruction.world import WorldStore
        from reconstruction.player import PlayerState
        from tests.support.world import map_packet,actor_packet
        world=WorldStore();store=DialogueStore(world=world)
        def consume(event):
            event=replace(event,connection='flow-a',flow_id='flow-a')
            world.apply(event);store.apply(event)
        consume(map_packet('test.gat'));consume(actor_packet(name='Speaker'))
        world.player_maps.states[(0,'flow-a')]=PlayerState(0,'flow-a',actor_id=9000,map_name='test.gat')
        consume(overhead_event(actor=9000,text='outside'))
        consume(packet(0x90,struct.pack('<IB',42,1),'SEND'))
        consume(packet(0xb4,struct.pack('<I',42)+b'hello\0'))
        consume(overhead_event(actor=9000,text='during'))
        consume(packet(0xb5,struct.pack('<I',42)))
        consume(overhead_event(actor=9000,text='waiting'))
        consume(packet(0xb9,struct.pack('<I',42),'SEND'))
        consume(packet(0xb6,struct.pack('<I',42)))
        consume(overhead_event(actor=9000,text='closing'))
        consume(packet(0x146,struct.pack('<I',42),'SEND'))
        consume(overhead_event(actor=9000,text='after'))
        rows=store.presentation_observations
        self.assertEqual([row['context'] for row in rows],['outside_dialogue','during_dialogue','input_wait','close_wait','outside_dialogue'])
        for row in rows:
            self.assertEqual(row['entity_kind'],'PLAYER')
            self.assertEqual(row['actor_id'],9000)
        for row in rows[1:4]:
            self.assertEqual(row['conversation_id'],1)
            self.assertEqual(row['conversation_actor_id'],42)
            self.assertFalse(row['cause_confirmed'])
            self.assertEqual(row['npc'],{})
        self.assertNotIn('conversation_id',rows[0]);self.assertNotIn('conversation_id',rows[-1])
        item=store.sessions[0]
        self.assertFalse(item.parallel_presentations)
        self.assertFalse(item.external_presentations)
        self.assertNotIn('showmessage',AurigaRenderer().render(item))
        self.assertFalse(build_merged([('',item)])['excluded'])
        consume(packet(0x90,struct.pack('<IB',42,1),'SEND'))
        world.player_maps.states[(0,'flow-a')].map_name='different.gat'
        consume(overhead_event(actor=9000,text='different map'))
        self.assertEqual(store.presentation_observations[-1]['context'],'outside_dialogue')
        self.assertNotIn('conversation_id',store.presentation_observations[-1])
        world.player_maps.states[(0,'other')]=PlayerState(0,'other',actor_id=9000,map_name='test.gat')
        other=replace(overhead_event(actor=9000),connection='other',flow_id='other')
        world.apply(other);store.apply(other)
        self.assertNotIn('conversation_id',store.presentation_observations[-1])


    def test_repeat_review_groups_complete_identical_paths_and_keeps_observed_differences(self):
        from copy import deepcopy
        from reconstruction.player_notification_review import review_player_notification_repeats
        from tests.support.event_trials import player_notification_trial
        contributions=[];rows=[]
        for session,text in ((1,'one'),(2,'two'),(3,None)):
            contribution,notices=player_notification_trial(session,text)
            contributions.append(contribution);rows+=notices
        before=deepcopy((contributions,rows))
        report=review_player_notification_repeats(contributions,rows)
        self.assertEqual(len(report['groups']),1)
        group=report['groups'][0]
        self.assertEqual(group['status'],'observed_difference')
        self.assertEqual(len(group['variants']),3)
        self.assertEqual([v['notification_count'] for v in group['observations']],[1,1,0])
        self.assertFalse(report['cause_confirmed']);self.assertFalse(report['missing_packet_inferred'])
        self.assertFalse(report['command_generation'])
        self.assertEqual((contributions,rows),before)
        rows[1]['fields']['text']='one'
        same=review_player_notification_repeats(contributions[:2],rows)['groups'][0]
        self.assertEqual(same['status'],'observed_match')
        self.assertNotEqual(same['observations'][0]['notifications'][0]['target_actor_id'],same['observations'][1]['notifications'][0]['target_actor_id'])
        rows[1]['context']='input_wait'
        self.assertEqual(review_player_notification_repeats(contributions[:2],rows)['groups'][0]['status'],'observed_difference')
        other,notices=player_notification_trial(4,'one',choice=2)
        separated=review_player_notification_repeats([contributions[0],other],rows+notices)
        self.assertEqual(len(separated['groups']),2)
        self.assertTrue(all(g['status']=='insufficient_observations' for g in separated['groups']))

    def test_repeat_review_excludes_partial_wait_and_foreign_source_instead_of_counting_absence(self):
        from copy import deepcopy
        from dataclasses import asdict
        from tests.unit.test_timeout_merging import trial
        from tests.support.event_trials import player_notification_trial
        from reconstruction.player_notification_review import review_player_notification_repeats
        good,rows=player_notification_trial(1)
        partial=trial(identifier=8)
        incomplete=deepcopy(good);incomplete['conversation']['id']=2
        incomplete['conversation']['steps'].pop()
        incomplete['conversation']['steps'][-1].pop('reply')
        foreign=dict(good,source_ref='foreign.jsonl')
        report=review_player_notification_repeats([good,deepcopy(good),
            dict(conversation=asdict(partial),source_ref='capture-0.jsonl'),incomplete,foreign],rows,{1:'capture-1.jsonl'})
        self.assertEqual(report['duplicate_observations'],1)
        self.assertEqual(report['groups'][0]['status'],'insufficient_observations')
        self.assertEqual(len(report['groups'][0]['observations']),1)
        self.assertEqual({r['reason'] for r in report['excluded']},{'unanswered_termination','incomplete_wait','source_mismatch'})
        for change,reason in (({'after_step_index':99},'notification_scope_or_order'),
                              ({'speech_origin':{}},'self_actor_unconfirmed'),
                              ({'speech_origin':{'self_actor_confirmed':True,'reason':'unsupported_layout'}},'notification_origin_unconfirmed'),
                              ({'timestamp':float('nan')},'notification_time_invalid'),
                              ({'timestamp':999},'notification_time_invalid')):
            invalid=dict(rows[0],**change)
            checked=review_player_notification_repeats([good],[invalid])
            self.assertEqual(checked['groups'],[])
            self.assertEqual(checked['excluded'][0]['reason'],reason)
        conflict=deepcopy(rows[0]);conflict['fields']['text']='different'
        checked=review_player_notification_repeats([good],rows+[conflict])
        self.assertEqual(checked['excluded'][0]['reason'],'conflicting_notification_evidence')

