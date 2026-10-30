import struct
import unittest
from copy import deepcopy
from dataclasses import replace

from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.branches import build_merged
from reconstruction.auriga import AurigaRenderer
from tests.support.world import map_packet, actor_packet, packet
from tests.support.display import variable


class ExternalPresentationTests(unittest.TestCase):
    def test_interrupted_dialogue_keeps_external_candidate_after_its_last_body_step(self):
        store, consume = self.setup_store()
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
        consume(packet(0xc0, struct.pack('<IB', 43, 7)))
        consume(packet(0x90, struct.pack('<IB', 43, 1), direction='SEND'))
        item = store.sessions[0]
        self.assertEqual(item.status, 'interrupted')
        self.assertIn('// emotion 7,', AurigaRenderer().render(item))

    def test_external_candidates_do_not_bind_to_removed_or_reused_conversation_actor(self):
        for reuse in (False, True):
            store, consume = self.setup_store()
            consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
            original = store.sessions[0]
            consume(packet(0x80, struct.pack('<IB', 42, 0)))
            if reuse:
                consume(actor_packet(actor_id=42, name='Reused'))
            consume(packet(0xc0, struct.pack('<IB', 43, 7)))
            self.assertFalse(original.external_presentations)
            self.assertEqual(store.presentation_observations[-1]['context'], 'outside_dialogue')
            self.assertEqual(store.presentation_observations[-1]['actor_id'], 43)
            if reuse:
                consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
                consume(packet(0xc0, struct.pack('<IB', 43, 8)))
                candidate = store.sessions[-1].external_presentations[0]
                self.assertEqual(candidate['conversation_entity_key'][-1], 2)
                self.assertEqual(candidate['target_entity_key'][-1], 1)
                self.assertFalse(original.external_presentations)

    def test_target_reappearance_keeps_old_evidence_and_rejects_tampered_generation_keys(self):
        store, consume = self.setup_store()
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
        consume(packet(0xc0, struct.pack('<IB', 43, 7)))
        first = deepcopy(store.sessions[0].external_presentations[0])
        consume(packet(0x80, struct.pack('<IB', 43, 0)))
        consume(packet(0xc0, struct.pack('<IB', 43, 8)))
        self.assertEqual(len(store.sessions[0].external_presentations), 1)
        self.assertEqual(store.presentation_observations[-1]['context'], 'outside_dialogue')
        consume(actor_packet(actor_id=43, name='NewTarget'))
        consume(packet(0xc0, struct.pack('<IB', 43, 9)))
        consume(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(item.external_presentations[0], first)
        self.assertEqual(item.external_presentations[1]['npc']['name'], 'NewTarget')
        self.assertEqual([row['target_entity_key'][-1] for row in item.external_presentations], [1, 2])
        self.assertFalse(build_merged([('log', item)])['excluded'])
        for key in ('target_entity_key', 'conversation_entity_key'):
            changed = deepcopy(item)
            changed.external_presentations[0][key][-1] += 1
            self.assertTrue(build_merged([('log', changed)])['excluded'])
            with self.assertRaises(ValueError):
                AurigaRenderer().render(changed)

    def setup_store(self, **options):
        world = WorldStore()
        store = DialogueStore(world=world, **options)
        def consume(event):
            world.apply(event)
            store.apply(event)
        for event in (map_packet('1@toy.gat'), actor_packet(name='Speaker'),
                      actor_packet(actor_id=43, name='Target'), actor_packet(actor_id=44, actor_type=5)):
            consume(event)
        return store, consume

    def test_external_npc_candidates_preserve_target_origin_uncertainty_and_do_not_interrupt_input(self):
        store, consume = self.setup_store()
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
        consume(packet(0xb5, struct.pack('<I', 42)))
        events = [packet(0xc0, struct.pack('<IB', 43, 7)),
                  packet(0x19b, struct.pack('<II', 43, 99)),
                  packet(0x1d3, b'cue.wav'.ljust(24, b'\0') + struct.pack('<BII', 1, 50, 43)),
                  variable(0x8b3, struct.pack('<I', 43) + b'overhead\0', 'flow-a'),
                  variable(0x8d, struct.pack('<I', 43) + b'unit words\0', 'flow-a')]
        for event in events:
            consume(event)
        # Unknown, MOB and other-flow targets stay outside this dialogue.
        consume(packet(0xc0, struct.pack('<IB', 999, 8)))
        consume(packet(0xc0, struct.pack('<IB', 44, 8)))
        consume(packet(0xc0, struct.pack('<IB', 43, 8), connection='other'))
        consume(packet(0xb9, struct.pack('<I', 42), direction='SEND'))
        consume(packet(0xb6, struct.pack('<I', 42)))
        item = store.sessions[0]
        self.assertEqual(store.issue_count, 0)
        self.assertEqual(len(store.sessions), 1)
        self.assertEqual(len(item.external_presentations), 5)
        self.assertEqual(item.steps[2]['reply_to'], 1)
        self.assertTrue(all(row['actor_id'] == 43 and row['conversation_actor_id'] == 42
                            and row['npc']['name'] == 'Target' and not row['cause_confirmed']
                            for row in item.external_presentations))
        before = deepcopy(item)
        text = AurigaRenderer().render(item)
        self.assertIn('// emotion 7,getmdnpcname("Target");', text)
        self.assertIn('// misceffect 99,getmdnpcname("Target");', text)
        self.assertIn('// showmessage "overhead",getmdnpcname("Target");', text)
        self.assertIn('unittalk getnpcid(0,getmdnpcname("Target")),"unit words";', text)
        self.assertIn('soundeffectにはNPC対象引数がない', text)
        self.assertTrue(all(not line.strip().startswith(('emotion ', 'misceffect ', 'showmessage ', 'soundeffect '))
                            for line in text.splitlines()))
        self.assertEqual(item, before)

    def test_external_presence_values_and_target_conflicts_participate_in_repeated_review(self):
        for change in ('missing', 'value', 'target'):
            trials = []
            for number in (0, 1):
                store, consume = self.setup_store()
                consume(actor_packet(actor_id=45, name='Another'))
                consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
                consume(replace(variable(0xb4, struct.pack('<I', 42) + b'hello\0', 'flow-a'), timestamp=1))
                if not (number and change == 'missing'):
                    consume(packet(0xc0, struct.pack('<IB', 45 if number and change == 'target' else 43,
                                                    8 if number and change == 'value' else 7)))
                consume(packet(0xb6, struct.pack('<I', 42)))
                trials.append((str(number), store.sessions[0]))
            report = build_merged(trials)
            self.assertFalse(report['excluded'])
            group = report['groups'][0]
            self.assertEqual(group['presentation_check']['conflicts'], 1)
            text = AurigaRenderer().render_merged(group)
            self.assertIn('要確認', text)
            self.assertIn('外部演出', text)
            trials[0][1].external_presentations[0]['flow_id'] = 'wrong'
            self.assertTrue(build_merged(trials)['excluded'])

    def test_unit_talk_layout_and_external_capacity_remain_bounded(self):
        valid = variable(0x8d, struct.pack('<I', 43) + b'hello\0', 'flow-a')
        self.assertEqual(decode_dialogue(valid), ('unittalk', 43, {'text': 'hello'}))
        for event in (replace(valid, raw=valid.raw[:-1]), variable(0x8d, struct.pack('<I', 43) + b'\x81\0')):
            with self.assertRaises(ValueError):
                decode_dialogue(event)
        self.assertIsNone(decode_dialogue(replace(valid, direction='SEND')))
        store, consume = self.setup_store(max_presentations=1)
        consume(packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'))
        consume(valid)
        consume(valid)
        self.assertEqual(len(store.sessions[0].external_presentations), 1)
        self.assertEqual(store.presentation_dropped, 1)

    def test_self_player_speech_matches_send_without_inferring_script_origin(self):
        from reconstruction.player import PlayerState
        store,consume=self.setup_store()
        store.world.player_maps.states[(0,'flow-a')]=PlayerState(0,'flow-a',actor_id=9000)
        def chat(pid,text=b'Player : hello',actor=9000,time=2,direction='RECV',connection='flow-a'):
            body=(struct.pack('<I',actor) if pid==0x8d else b'')+text+b'\0'
            return replace(variable(pid,body,connection),timestamp=time,direction=direction)
        consume(chat(0x8c,time=2,direction='SEND'))
        consume(chat(0x8e,time=2.1))
        first=store.presentation_observations[-1]
        self.assertEqual(first['kind'],'player_chat')
        self.assertEqual(first['entity_kind'],'PLAYER')
        self.assertEqual(first['actor_id'],9000)
        self.assertEqual(first['speech_origin']['origin'],'send_match_candidate')
        self.assertFalse(first['speech_origin']['cause_confirmed'])
        self.assertEqual(first['speech_origin']['send_packet_id'],0x8c)
        consume(chat(0x8d,time=3))
        self.assertEqual(store.presentation_observations[-1]['speech_origin']['origin'],'unresolved')
        consume(chat(0x8c,time=4,direction='SEND'))
        consume(chat(0x8d,actor=43,time=4.1))
        self.assertEqual(store.presentation_observations[-1]['speech_origin']['origin'],'unresolved')
        consume(chat(0x8d,time=4.2))
        self.assertEqual(store.presentation_observations[-1]['speech_origin']['origin'],'send_match_candidate')
        self.assertFalse(store.sessions)
        self.assertFalse(store.presentation_observations[-1]['npc'])

    def test_player_speech_scope_ambiguity_missing_capture_and_bounded_tracking(self):
        from reconstruction.speech_origin import SpeechOrigin
        tracker=SpeechOrigin()
        sent=replace(variable(0x8c,b'Player : hello\0','flow-a'),direction='SEND',timestamp=1)
        received=replace(variable(0x8d,struct.pack('<I',9000)+b'Player : hello\0','flow-a'),timestamp=2)
        tracker.sent(sent,0,1,9000)
        for event,session,actor,owner in ((received,1,9000,9000),(replace(received,connection='other'),0,9000,9000),
                                        (received,0,43,9000),(received,0,9000,None),
                                        (replace(received,timestamp=10),0,9000,9000),
                                        (replace(received,timestamp=.5),0,9000,9000)):
            self.assertEqual(tracker.received(event,session,2,actor,owner)['origin'],'unresolved')
        tracker.sent(sent,0,2,9000)
        self.assertEqual(tracker.received(received,0,3,9000,9000)['origin'],'ambiguous_send_candidates')
        self.assertEqual(len(tracker.pending),0)
        for index in range(100):tracker.sent(sent,0,index,9000)
        self.assertEqual(len(tracker.pending),64)
        before=len(tracker.pending)
        tracker.sent(replace(sent,raw=sent.raw[:-1]),0,100,9000)
        self.assertEqual(len(tracker.pending),before)
        changed=replace(received,raw=received.raw[:-1])
        result=tracker.received(changed,0,101,9000,9000)
        self.assertEqual(result['origin'],'unresolved')
        self.assertEqual(result['reason'],'unsupported_layout')

    def test_speech_replay_audit_counts_all_receives_bounds_details_and_checks_inputs(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tools.audit_player_speech import audit
        events=[packet(0x283,struct.pack('<I',9000)),
                replace(variable(0x8c,b'Player : hello\0','flow-a'),direction='SEND',timestamp=2),
                replace(variable(0x8e,b'Player : hello\0','flow-a'),timestamp=2.1),
                replace(variable(0x8d,struct.pack('<I',43)+b'hello\0','flow-a'),timestamp=3)]
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'capture.jsonl';definitions=Path(folder)/'PacketLength.txt'
            source.write_text(json.dumps({'kind':'session_start','schema':1,'record_payload':True})+'\n',encoding='utf-8')
            definitions.write_text('0283 6\n008C -1\n008D -1\n008E -1\n',encoding='utf-8')
            original=source.read_bytes()
            def replay_mock(log,lengths,on_packet):
                for event in events:on_packet(event)
                return {'complete':False}
            with patch('tools.audit_player_speech.replay',side_effect=replay_mock):
                result=audit(source,definitions,max_details=1)
            self.assertEqual(result['packet_count'],4)
            self.assertEqual(result['receive_origin_counts'],{'send_match_candidate':1,'unresolved':1})
            self.assertEqual(result['receive_reason_counts'],{'unique_send_match':1,'different_actor':1})
            self.assertEqual(result['details'][0]['speech_origin']['send_packet_index'],1)
            self.assertEqual(result['omitted_details'],1)
            self.assertFalse(result['script_origin_inferred'])
            self.assertFalse(result['live_input_verified'])
            self.assertEqual(source.read_bytes(),original)
            def changed(log,lengths,on_packet):
                source.write_bytes(original+b'{}\n')
                return {}
            with patch('tools.audit_player_speech.replay',side_effect=changed),self.assertRaises(ValueError):
                audit(source,definitions)
            with self.assertRaises(ValueError):audit(source,definitions,max_details=True)

    def test_real_capture_chat_layout_without_nul_and_self_overhead_notification(self):
        from reconstruction.player import PlayerState
        from reconstruction.speech_origin import payload
        store,consume=self.setup_store()
        store.world.player_maps.states[(0,'flow-a')]=PlayerState(0,'flow-a',actor_id=4631724)
        send=replace(packet(0x8c),raw=bytes.fromhex('8c00100082a53c82a53c202a203a2061'),timestamp=2,direction='SEND')
        receive=replace(send,packet_id=0x8e,raw=bytes.fromhex('8e00100082a53c82a53c202a203a2061'),timestamp=2.1,direction='RECV')
        consume(send);consume(receive)
        self.assertEqual(store.presentation_observations[-1]['speech_origin']['origin'],'send_match_candidate')
        self.assertEqual(payload(send),payload(receive))
        consume(replace(send,timestamp=3))
        overhead=replace(packet(0x8b3),raw=bytes.fromhex('b3081800acac4600965c919682b582bd968297cd20212100'),timestamp=3.1)
        consume(overhead)
        record=store.presentation_observations[-1]
        self.assertEqual(record['kind'],'overhead')
        self.assertEqual(record['entity_kind'],'PLAYER')
        self.assertEqual(record['speech_origin']['reason'],'non_chat_notification')
        self.assertFalse(record['speech_origin']['cause_confirmed'])
        self.assertEqual(len(store.speech.pending),1)
        self.assertIsNone(payload(replace(send,raw=send.raw[:6]+b'\0'+send.raw[7:])))
        self.assertIsNone(payload(replace(receive,raw=receive.raw[:-1])))
