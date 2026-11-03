import json
from pathlib import Path
import struct
from unittest.mock import patch

from tests.support.qt import WindowTestCase
from tests.support.world import actor_packet, map_packet
from tests.support.dialogue import packet


class TimingComparisonGuiTests(WindowTestCase):
    def test_source_only_change_or_equal_revision_store_replacement_blocks_old_evidence(self):
        from copy import deepcopy
        from PySide6.QtCore import QItemSelectionModel
        from reconstruction.dialogue import DialogueStore
        from tests.support.event_trials import observation
        panel = self.window.dialogue_panel.event_trials
        for change in ('source', 'store', 'revision'):
            with self.subTest(change=change):
                store = DialogueStore()
                store.presentation_observations = [observation(start + offset)
                    for start in (0, 10, 20) for offset in (0, 1)]
                store.source_refs = {0:'original.jsonl'}
                panel.store = store
                panel.refresh()
                panel.window.setValue(2000)
                for index in (0, 2, 4):
                    panel.table.selectionModel().select(panel.table.model().index(index, 0),
                        QItemSelectionModel.Select | QItemSelectionModel.Rows)
                panel.compute()
                self.assertIsNotNone(panel.report)
                panel.trials.selectRow(0)
                panel.events.selectRow(0)
                panel.table.setCurrentCell(0,0, QItemSelectionModel.NoUpdate)
                if change == 'source':
                    store.source_refs[0] = 'other.jsonl'
                elif change == 'store':
                    replacement = DialogueStore()
                    replacement.revision = store.revision
                    replacement.presentation_observations = deepcopy(store.presentation_observations)
                    replacement.source_refs = dict(store.source_refs)
                    panel.store = replacement
                else:
                    store.revision += 1
                with patch.object(panel,'on_source') as navigate:
                    panel.jump()
                    panel.jump_speech_send()
                    panel.jump_event()
                    panel.jump_reference_event()
                    panel.jump_excluded_event()
                    panel.jump_timing_sample()
                navigate.assert_not_called()
                self.assertIsNone(panel.report)
                with patch('gui.event_trials.QFileDialog.getSaveFileName') as choose, \
                     patch('gui.event_trials.QMessageBox.information'):
                    panel.save()
                    panel.save_anchors()
                choose.assert_not_called()
                panel.compute()
                self.assertIsNone(panel.report)
                panel.refresh()
                self.assertEqual(panel.snapshot_observation_key, panel.observation_key())

    def test_marker_and_effect_target_notes_do_not_replace_observations(self):
        from copy import deepcopy
        from tests.support.event_trials import observation
        panel = self.window.dialogue_panel.event_trials
        rows = [observation(1, kind='viewpoint', packet_id=0x144,
                    fields={'kind':1,'x':100,'y':200,'marker_id':7,'color':0x123456}),
                observation(2, kind='effect_value', packet_id=0x284,
                    fields={'effect_id':333,'value':9}),
                observation(3, kind='effect_remove', packet_id=0xb0d, fields={'value':333})]
        before = deepcopy(rows)
        self.window.dialogues.presentation_observations = rows
        self.window.dialogues.revision += 1
        panel.refresh()
        for index, label, explanation in ((0,'通知NPC:','受信'),
                                          (1,'効果対象:','エフェクトの対象ID'),
                                          (2,'効果対象:','エフェクトの対象ID')):
            panel.table.selectRow(index)
            self.assertIn(label, panel.table.item(index,3).text())
            self.assertIn(explanation, panel.speech_note.text() + panel.speech_note.toolTip())
        self.assertEqual(self.window.dialogues.presentation_observations, before)

    def test_self_speech_origin_explanation_and_send_navigation_respect_stale_rows(self):
        from dataclasses import replace
        from tests.support.display import variable
        w=self.window;panel=w.dialogue_panel.event_trials
        w.add_packet(packet(0x283,struct.pack('<I',9000),flow='game',connection='game',timestamp=1))
        sent=replace(variable(0x8c,b'Player : hello\0','game'),flow_id='game',direction='SEND',timestamp=2)
        received=replace(variable(0x8e,b'Player : hello\0','game'),flow_id='game',timestamp=2.1)
        w.add_packet(sent);w.add_packet(received)
        panel.refresh();panel.table.selectRow(0)
        self.assertIn('本人入力のSEND関連候補',panel.speech_note.text())
        self.assertIn('確定するものではありません',panel.speech_note.text())
        self.assertTrue(panel.speech_source.isEnabled())
        panel.jump_speech_send()
        self.assertEqual(w.selected_packet_index(),1)
        w.add_packet(replace(received,timestamp=3))
        with patch.object(panel,'on_source') as navigate:panel.jump_speech_send()
        navigate.assert_not_called()
        self.assertFalse(panel.speech_source.isEnabled())
        self.assertIn('一覧を更新',panel.speech_note.text())
        panel.refresh();panel.table.selectRow(1)
        self.assertFalse(panel.speech_source.isEnabled())
        self.assertIn('条件を満たすSENDがありません',panel.speech_note.text())
        evidence=panel.rows[1]['speech_origin']
        for origin,reason,phrase in (('unresolved','self_actor_unknown','本人ActorIDが未取得'),
                                    ('unresolved','different_actor','異なる発言元'),
                                    ('unresolved','unsupported_layout','未対応'),
                                    ('ambiguous_send_candidates','multiple_matching_sends','一意に照合できません')):
            evidence.update(origin=origin,reason=reason,candidate_count=2)
            panel.show_speech_origin()
            self.assertIn(phrase,panel.speech_note.text())
            with patch.object(panel,'on_source') as navigate:panel.jump_speech_send()
            navigate.assert_not_called()
        evidence.update(origin='send_match_candidate',self_actor_confirmed=True,association_only=True,
                        send_packet_id=0x8c,send_packet_index=True)
        panel.show_speech_origin();self.assertFalse(panel.speech_source.isEnabled())
        evidence['send_packet_index']=9999
        panel.show_speech_origin();self.assertFalse(panel.speech_source.isEnabled())
        panel.table.clearSelection();panel.show_speech_origin()
        self.assertFalse(panel.speech_source.isEnabled())

    def test_adoption_status_explains_unsupported_trials_without_changing_comparison(self):
        from copy import deepcopy
        from tests.support.event_trials import repeated_report
        panel=self.window.dialogue_panel.event_trials
        self.assertFalse(panel.adopt_button.isEnabled())
        report=repeated_report('unittalk')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields']={'text':'hello'}
        report['trials'][1]['events'][1]['observation'].update(kind='music',fields={'music':'theme.mp3','mode':None})
        report['trials'][2]['events'][1]['observation'].update(kind='player_chat',entity_kind='PLAYER',npc={},
            speech_origin={'origin':'send_match_candidate','send_packet_index':10,'cause_confirmed':False})
        before=deepcopy(report)
        panel.report=report;panel.report_key=panel.current_key()
        panel.show_trial_summary()
        self.assertTrue(panel.adopt_button.isEnabled())
        self.assertIn('全時刻の入力と確認が必要',panel.adoption_note.text())
        panel.trials.selectRow(1)
        self.assertFalse(panel.adopt_button.isEnabled())
        self.assertIn('music: 1件',panel.adoption_note.text())
        self.assertEqual(panel.events.rowCount(),2)
        panel.trials.selectRow(2)
        self.assertFalse(panel.adopt_button.isEnabled())
        self.assertIn('player_chat: 1件',panel.adoption_note.text())
        panel.events.selectRow(1)
        self.assertIn('send_match_candidate',panel.event_difference.toPlainText())
        panel.trials.selectRow(0)
        self.assertTrue(panel.adopt_button.isEnabled())
        self.assertEqual(report,before)
        for mode in ('dialogue_start','map_arrival'):
            panel.report=dict(report,anchor_type=mode);panel.report_key=panel.current_key()
            panel.show_trial_summary()
            self.assertFalse(panel.adopt_button.isEnabled())
            self.assertIn('直接変換対象外',panel.adoption_note.text())
        panel.window.setValue(panel.window.value()+1)
        self.assertFalse(panel.adopt_button.isEnabled())
        self.assertIsNone(panel.report)
        self.assertIn('比較して',panel.adoption_note.text())

    def test_multi_log_resume_evidence_navigation_and_retention_limits(self):
        from copy import deepcopy
        from PySide6.QtCore import QItemSelectionModel
        from tests.support.event_trials import observation
        from tests.unit.test_event_trial_selection import raw_log
        panel=self.window.dialogue_panel.event_trials
        store=self.window.dialogues
        sources={}
        original=[]
        for session in range(3):
            source=Path(self.log_folder.name)/f'capture-{session}.jsonl'
            raw_log(source,str(session));sources[session]=str(source)
            for offset,value,context in ((0,7,'outside_dialogue'),(1,9,'outside_dialogue'),(1.5,8,'close_wait')):
                original.append(observation(offset,value,capture_session=session,
                    flow_id=f'flow-{session}',packet_index=session*100+int(offset*10),context=context))
        store.presentation_observations=deepcopy(original)
        store.source_refs=sources
        store.revision+=1
        panel.refresh();panel.window.setValue(2000)
        for index in (0,3,6):
            panel.table.selectionModel().select(panel.table.model().index(index,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        target=Path(self.log_folder.name)/'multi-anchors.json'
        with patch('gui.event_trials.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            panel.save_anchors()
        remap={0:9,1:4,2:1}
        store.presentation_observations=[dict(row,capture_session=remap[row['capture_session']],
            packet_index=row['packet_index']+1000) for row in original]
        store.presentation_observations.sort(key=lambda row:row['capture_session'])
        store.source_refs={remap[key]:value for key,value in sources.items()}
        store.presentation_dropped=3;store.map_anchor_dropped=2
        store.revision+=1
        with patch('gui.event_trials.QFileDialog.getOpenFileName',return_value=(str(target),'')):
            panel.load_anchors()
        self.assertEqual(panel.selected_indices(),[0,3,6])
        self.assertIn('MAP基準点の未保存 2件',panel.note.text())
        panel.compute()
        self.assertEqual(panel.report['status'],'repeated_consistent')
        self.assertEqual(panel.report['presentation_dropped'],3)
        self.assertEqual(panel.report['map_anchor_dropped'],2)
        self.assertIn('各試行への帰属は未確定',panel.note.text())
        for trial_index,session in enumerate((1,4,9)):
            panel.trials.selectRow(trial_index)
            anchor=panel.report['trials'][trial_index]['anchor']
            expected_path=store.source_refs[session]
            self.assertIn(expected_path,panel.trials.item(trial_index,5).toolTip())
            panel.events.selectRow(1)
            self.assertIn(f'取得世代 {session}',panel.event_difference.toPlainText())
            self.assertIn(expected_path,panel.events.item(1,3).toolTip())
            with patch.object(panel,'on_source') as navigate:
                panel.jump_event()
                navigate.assert_called_once_with(anchor['packet_index']+10)
            panel.exclusions.selectRow(0)
            self.assertIn(expected_path,panel.exclusions.item(0,4).toolTip())
            with patch.object(panel,'on_source') as navigate:
                panel.jump_excluded_event()
                navigate.assert_called_once_with(anchor['packet_index']+15)
        panel.events.selectRow(1)
        with patch.object(panel,'on_source') as navigate:
            panel.jump_reference_event()
            navigate.assert_called_once_with(1210)
        store.presentation_dropped=0;store.map_anchor_dropped=0
        panel.compute()
        self.assertIn('0件でも通信欠落・窓の全件取得を保証しません',panel.note.text())
        self.assertFalse(panel.report['coverage_verified'])

    def test_target_difference_and_excluded_packets_have_separate_navigation(self):
        from copy import deepcopy
        from PySide6.QtCore import QItemSelectionModel
        from tests.support.event_trials import observation
        panel=self.window.dialogue_panel.event_trials
        store=self.window.dialogues
        for time,generation in ((0,1),(10,2),(20,3)):
            store.map_arrival_anchors.append(dict(kind='map_arrival',anchor_type='map_arrival',fields={},
                context='comparison_anchor',timestamp=time,packet_index=int(time*100),capture_session=0,
                flow_id='flow',actor_id=None,entity_kind='MAP',target_observed=False,
                npc=dict(map_name='test.gat',map_generation=generation)))
        first=observation(.5,9)
        second=observation(10.5,9);second['npc'].update(name='Other',map_generation=2)
        close=observation(10.8,7,context='close_wait');close['npc']['map_generation']=2
        store.presentation_observations=[first,second,close]
        store.revision+=1
        panel.window.setValue(2000)
        panel.anchor_mode.setCurrentIndex(panel.anchor_mode.findData('map_arrival'))
        for index,row in enumerate(panel.rows):
            if row.get('anchor_type')=='map_arrival':
                panel.table.selectionModel().select(panel.table.model().index(index,0),
                    QItemSelectionModel.Select|QItemSelectionModel.Rows)
        panel.compute()
        original=deepcopy(panel.report)
        panel.trials.selectRow(1)
        self.assertIn('対象が異なる',panel.trials.item(1,6).text())
        self.assertIn('Other',panel.events.item(1,4).text())
        self.assertEqual(panel.events.columnCount(),7)
        self.assertEqual(panel.events.horizontalHeaderItem(5).text(),'タイマー扱い')
        self.assertEqual(panel.events.item(1,5).text(),'実行命令候補（command）')
        self.assertEqual(panel.events.item(1,6).text(),'対象が異なる（target_changed）')
        self.assertEqual(panel.events.item(1,6).toolTip(),'target_changed')
        panel.events.selectRow(1)
        self.assertIn('選択試行: Other',panel.event_difference.toPlainText())
        self.assertIn('参照試行: NPC',panel.event_difference.toPlainText())
        with patch.object(panel,'on_source') as source:
            panel.jump_reference_event();panel.jump_event()
        self.assertEqual([c.args[0] for c in source.call_args_list],[50,1050])
        self.assertEqual(panel.exclusions.item(0,3).text(),'close応答待ち中（close_wait）')
        self.assertEqual(panel.exclusions.item(0,3).toolTip(),'close_wait')
        panel.exclusions.selectRow(0)
        with patch.object(panel,'on_source') as source:panel.jump_excluded_event()
        source.assert_called_once_with(1080)
        panel.trials.selectRow(2)
        self.assertEqual(panel.events.item(1,1).text(),'未観測')
        self.assertEqual(panel.events.item(1,5).text(),'—')
        self.assertEqual(panel.events.item(1,6).text(),'参照側のみ観測（unobserved）')
        panel.events.selectRow(1)
        self.assertTrue(panel.reference_source.isEnabled())
        self.assertEqual(panel.report,original)
        store.revision+=1
        with patch.object(panel,'on_source') as source:panel.jump_reference_event()
        source.assert_not_called()
        self.assertEqual(panel.exclusions.rowCount(),0)
        self.assertEqual(panel.event_difference.toPlainText(),'')

    def test_dialogue_and_map_anchor_modes_show_scope_and_packet_navigation(self):
        from PySide6.QtCore import QItemSelectionModel
        w=self.window
        for repeat in range(2):
            stamp=repeat*10
            w.add_packet(map_packet('test.gat',timestamp=stamp))
            w.add_packet(actor_packet(timestamp=stamp+.1))
            for event in (packet(0x90,struct.pack('<IB',42,1),'SEND',flow=None,connection='flow-a',timestamp=stamp+.2),
                          packet(0xb4,struct.pack('<I',42)+b'hello\0',flow=None,connection='flow-a',timestamp=stamp+.3),
                          packet(0xc0,struct.pack('<IB',42,9),flow=None,connection='flow-a',timestamp=stamp+.35),
                          packet(0xb6,struct.pack('<I',42),flow=None,connection='flow-a',timestamp=stamp+.4),
                          packet(0x146,struct.pack('<I',42),'SEND',flow=None,connection='flow-a',timestamp=stamp+.5),
                          packet(0xc0,struct.pack('<IB',42,7),flow=None,connection='flow-a',timestamp=stamp+3)):
                w.add_packet(event)
        panel=w.dialogue_panel.event_trials
        panel.window.setValue(5000)
        for mode in ('dialogue_start','map_arrival'):
            panel.anchor_mode.setCurrentIndex(panel.anchor_mode.findData(mode))
            anchors=[i for i,row in enumerate(panel.rows) if row.get('anchor_type')==mode]
            self.assertEqual(len(anchors),2)
            for index in anchors:
                panel.table.selectionModel().select(panel.table.model().index(index,0),
                    QItemSelectionModel.Select|QItemSelectionModel.Rows)
            panel.compute()
            self.assertEqual(panel.report['anchor_type'],mode)
            self.assertEqual(panel.report['status'],'insufficient_repeats')
            self.assertEqual(len(panel.report['trials'][0]['events']),3 if mode=='dialogue_start' else 2)
            panel.table.setCurrentCell(anchors[0],0)
            with patch.object(panel,'on_source') as navigate:
                panel.jump()
            navigate.assert_called_once_with(panel.rows[anchors[0]]['packet_index'])
        w.npc_panel.set_records(reversed(w.world.records('NPC')))
        self.assertEqual([e.actor_id for e in w.npc_panel.model.rows],[42,42])

    def test_sound_music_progress_target_notes_are_view_only_and_keep_timer_restrictions(self):
        from copy import deepcopy
        from PySide6.QtCore import QItemSelectionModel
        from tests.support.event_trials import observation
        w=self.window;panel=w.dialogue_panel.event_trials
        rows=[]
        for start in (0,10):
            rows.extend([observation(start),
                observation(start+1,kind='sound',packet_id=0x1d3,fields={'sound':'test.wav','mode':0,'interval':0}),
                observation(start+1.2,kind='music',packet_id=0x7fe,actor_id=None,target_observed=False,entity_kind='unresolved',npc={},fields={'music':'theme.mp3','mode':None}),
                observation(start+1.4,kind='progressbar',packet_id=0x9d1,fields={'seconds':3,'color':0})])
        before=deepcopy(rows);w.dialogues.presentation_observations=rows;w.dialogues.revision+=1
        panel.refresh()
        panel.table.selectRow(1)
        self.assertIn('音源:',panel.table.item(1,3).text())
        self.assertIn('音源',panel.speech_note.text())
        self.assertIn('接続プレイヤー',panel.speech_note.toolTip())
        panel.table.selectRow(2);self.assertIn('対象ActorIDは未記録',panel.speech_note.text())
        panel.table.selectRow(3);self.assertIn('対象ID付き進捗',panel.speech_note.text())
        panel.table.clearSelection();panel.window.setValue(2000)
        for index in (0,4):panel.table.selectionModel().select(panel.table.model().index(index,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        panel.compute()
        self.assertEqual(panel.report['status'],'insufficient_repeats')
        self.assertFalse(panel.adopt_button.isEnabled())
        self.assertEqual(panel.events.item(1,5).text(),'タイマー拒否（rejected）')
        self.assertEqual(panel.events.item(2,5).text(),'タイマー拒否（rejected）')
        self.assertEqual(panel.events.item(3,5).text(),'タイマー拒否（rejected）')
        panel.events.selectRow(1);self.assertIn('音源の根拠',panel.event_difference.toPlainText())
        panel.events.selectRow(2);self.assertIn('対象ActorIDを含みません',panel.event_difference.toPlainText())
        panel.events.selectRow(3);self.assertIn('発生元',panel.event_difference.toPlainText())
        self.assertEqual(w.dialogues.presentation_observations,before)

    def test_music_window_comparison_displays_unassigned_music_and_packet_evidence(self):
        from copy import deepcopy
        from PySide6.QtCore import QItemSelectionModel
        from tests.support.event_trials import observation
        w = self.window
        rows = [observation(0), observation(1, kind='music', actor_id=None, target_observed=False,
                    entity_kind='unresolved', npc={}, fields={'music': 'theme.mp3', 'mode': None}),
                observation(10), observation(11, kind='music', actor_id=None, target_observed=False,
                    entity_kind='unresolved', npc={}, fields={'music': 'other.mp3', 'mode': 1})]
        w.dialogues.presentation_observations = deepcopy(rows)
        w.dialogues.revision += 1
        panel = w.dialogue_panel.event_trials
        panel.window.setValue(2000)
        panel.refresh()
        for index in (0, 2):
            panel.table.selectionModel().select(panel.table.model().index(index, 0),
                                               QItemSelectionModel.Select | QItemSelectionModel.Rows)
        panel.compute()
        self.assertEqual(panel.report['status'], 'observed_difference')
        panel.trials.selectRow(0)
        self.assertEqual(panel.events.item(1, 1).text(), 'BGM（対象未特定）')
        panel.events.selectRow(1)
        with patch.object(panel, 'on_source') as navigate:
            panel.jump_event()
        navigate.assert_called_once_with(100)
        self.assertEqual(w.dialogues.presentation_observations, rows)

    def test_effect_removal_timer_editor_requires_times_and_confirmation_and_labels_action(self):
        from tests.support.event_trials import repeated_report
        from gui.event_timer_editor import EventTimerEditor
        editor = EventTimerEditor(repeated_report('effect_remove'), 0, self.window)
        self.assertEqual(editor.table.item(1, 0).text(), 'エフェクト解除 9')
        self.assertFalse(editor.confirmed.isChecked())
        self.assertTrue(all(not field.text() for field in editor.times))
        editor.times[0].setText('100')
        editor.times[1].setText('1100')
        editor.confirmed.setChecked(True)
        editor.generate()
        self.assertIn('delmisceffect 9;', editor.preview.toPlainText())
        editor.close()

    def test_timer_editor_opens_extended_kinds_without_value_field(self):
        """GUI smoke: editor construction for kinds that lack fields['value']. Labels/export stay unit-tested."""
        from tests.support.event_trials import repeated_report
        from gui.event_timer_editor import EventTimerEditor
        cases = (
            ('event_marker', dict(x=1, y=2, state=3, kind=4)),
            ('progressbar', dict(seconds=5, color=0x112233)),
            ('overhead', dict(text='head')),
        )
        for kind, fields in cases:
            report = repeated_report('effect')
            for trial in report['trials']:
                event = trial['events'][1]
                event['association_basis'] = 'selected_timer_window_same_flow'
                event['observation'].update(kind=kind, fields=dict(fields))
                if kind == 'progressbar':
                    event['observation'].update(actor_id=None, target_observed=False,
                                                entity_kind='unresolved', npc={})
            editor = EventTimerEditor(report, 0, self.window)
            self.assertTrue(editor.table.item(1, 0).text())
            self.assertTrue(all(not field.text() for field in editor.times))
            editor.close()

    def test_self_unittalk_timer_editor_requires_manual_times_and_roundtrips_evidence(self):
        from copy import deepcopy
        from tests.support.event_trials import repeated_report
        from gui.event_timer_editor import EventTimerEditor
        report=repeated_report('unittalk')
        for trial in report['trials']:
            trial['events'][1]['observation']['fields']={'text':'こんにちは"NPC"'}
        before=deepcopy(report)
        editor=EventTimerEditor(report,0,self.window.dialogue_panel.event_trials)
        self.assertIn('unittalk こんにちは',editor.table.item(1,0).text())
        self.assertEqual([field.text() for field in editor.times],['',''])
        with self.assertRaises(ValueError):editor.document()
        for field,value in zip(editor.times,('100','1500')):field.setText(value)
        with self.assertRaises(ValueError):editor.document()
        editor.confirmed.setChecked(True);editor.generate()
        self.assertIn('OnTimer1500:',editor.preview.toPlainText())
        self.assertIn('unittalk '+json.dumps('こんにちは"NPC"',ensure_ascii=False)+';',editor.preview.toPlainText())
        path=Path(self.log_folder.name)/'unittalk-timer.json'
        with patch('gui.event_timer_editor.QFileDialog.getSaveFileName',return_value=(str(path),'')):
            editor.save()
        saved=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['manual_times_ms'],[100,1500])
        self.assertFalse(saved['automatic_start_generated'])
        editor.times[1].setText('1600')
        with patch('gui.event_timer_editor.QFileDialog.getOpenFileName',return_value=(str(path),'')):
            editor.load()
        self.assertEqual([field.text() for field in editor.times],['100','1500'])
        self.assertFalse(editor.confirmed.isChecked())
        self.assertEqual(report,before)
        editor.close();editor.deleteLater()

    def test_manual_timer_editor_accepts_announcement_with_explicit_times_and_confirmation(self):
        from tests.support.event_trials import repeated_report
        from gui.event_timer_editor import EventTimerEditor
        report = repeated_report('effect')
        for trial in report['trials']:
            event = trial['events'][1]
            event['association_basis'] = 'selected_timer_window_same_flow'
            event['observation'].update(kind='announcement', actor_id=None, target_observed=False,
                entity_kind='unresolved', npc={}, fields=dict(text='告知', broadcast_prefix=None))
        editor = EventTimerEditor(report, 0, self.window.dialogue_panel.event_trials)
        self.assertIn('announce 告知', editor.table.item(1, 0).text())
        self.assertTrue(all(not field.text() for field in editor.times))
        editor.times[0].setText('100')
        editor.times[1].setText('1100')
        with self.assertRaises(ValueError):
            editor.document()
        editor.confirmed.setChecked(True)
        editor.generate()
        self.assertIn('announce "告知",0;', editor.preview.toPlainText())
        destination = Path(self.log_folder.name) / 'announce-timer.json'
        with patch('gui.event_timer_editor.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            editor.save()
        with patch('gui.event_timer_editor.QFileDialog.getOpenFileName', return_value=(str(destination), '')):
            editor.load()
        self.assertFalse(editor.confirmed.isChecked())
        self.assertEqual([field.text() for field in editor.times], ['100', '1100'])
        editor.close()

    def test_comparison_exports_freeze_report_and_protect_inputs_and_existing_output(self):
        w = self.window
        for panel, module, key_name in ((w.dialogue_panel.timing_comparison, 'gui.timing_comparison', 'key'),
                                        (w.dialogue_panel.event_trials, 'gui.event_trials', 'report_key')):
            def prepare():
                panel.report = dict(observed=[1, 2], server_timer_confirmed=False)
                setattr(panel, key_name, panel.current_key())
            prepare()
            destination = Path(self.log_folder.name) / f'{module}.json'
            def choose(*args):
                panel.report['observed'].append(3)
                panel.report = None
                w.dialogues.revision += 1
                return str(destination), ''
            with patch(module + '.QFileDialog.getSaveFileName', side_effect=choose):
                panel.save()
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8')),
                             dict(observed=[1, 2], server_timer_confirmed=False))
            for protection in ('source', 'definitions', 'config', 'replacement'):
                w.dialogues.source_refs.clear()
                w.path.setText('')
                target = destination
                if protection == 'source':
                    w.dialogues.source_refs[0] = str(destination)
                elif protection == 'definitions':
                    w.path.setText(str(destination))
                elif protection == 'config':
                    target = Path(__file__).resolve().parents[2] / 'config' / 'auriga' / 'dialogue.json'
                prepare()
                before = target.read_bytes()
                with patch(module + '.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                        patch(module + '.QMessageBox.warning') as warning, \
                        patch('storage.observation_export.os.replace', side_effect=OSError('replace failed')) as replace:
                    panel.save()
                    warning.assert_called_once()
                    self.assertEqual(replace.call_count, int(protection == 'replacement'))
                self.assertEqual(target.read_bytes(), before)

    def test_comparison_exports_reject_nonfinite_values_and_keep_32_mib_utf8_limit(self):
        w = self.window
        for panel, module, key_name in ((w.dialogue_panel.timing_comparison, 'gui.timing_comparison', 'key'),
                                        (w.dialogue_panel.event_trials, 'gui.event_trials', 'report_key')):
            for value in (float('nan'), 'あ' * (32 * 1024 * 1024 // 3 + 1)):
                panel.report = dict(observed=value)
                setattr(panel, key_name, panel.current_key())
                with patch(module + '.QFileDialog.getSaveFileName') as choose, \
                        patch(module + '.QMessageBox.warning') as warning:
                    panel.save()
                    warning.assert_called_once()
                    choose.assert_not_called()
                panel.report = None

    def test_timer_entry_guards_and_real_comparison_changes_reject_old_editor(self):
        from copy import deepcopy
        from gui.event_timer_editor import EventTimerEditor
        from tests.support.event_trials import repeated_report
        panel=self.window.dialogue_panel.event_trials
        report=repeated_report('effect');before=deepcopy(report)
        for mode in ('dialogue_start','map_arrival','unknown'):
            panel.report=dict(report,anchor_type=mode)
            panel.report_key=panel.current_key()
            panel.show_trial_summary()
            with patch('gui.event_timer_editor.EventTimerEditor.exec') as opened,patch('gui.event_trials.QMessageBox.warning') as warning:
                panel.adopt_timer()
            opened.assert_not_called();warning.assert_called_once()
        for fields in ({'actor_id':99},{'context':'external_candidate'},{'context':'close_wait'},
                       {'target_observed':False},{'packet_index':None},{'kind':'music'}):
            changed=deepcopy(report)
            changed['trials'][0]['events'][1]['observation'].update(fields)
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                EventTimerEditor(changed,0,panel)
        with self.assertRaises(ValueError):
            EventTimerEditor(report,0,panel,is_current=lambda:False)
        for index in (-1,True,99):
            with self.subTest(index=index),self.assertRaises(ValueError):
                EventTimerEditor(report,index,panel)
        changes=(lambda:panel.window.setValue(panel.window.value()+1),
                 lambda:panel.anchor_mode.setCurrentIndex(panel.anchor_mode.findData('map_arrival')),
                 lambda:panel.include_actions.setChecked(not panel.include_actions.isChecked()),
                 lambda:setattr(panel.store,'revision',panel.store.revision+1),
                 lambda:setattr(panel,'report',deepcopy(report)))
        for change in changes:
            panel.report=report
            key=panel.current_key()
            editor=EventTimerEditor(report,0,panel,
                is_current=lambda:panel.report is report and panel.current_key()==key)
            for field,value in zip(editor.times,('100','1100')):field.setText(value)
            editor.confirmed.setChecked(True);editor.generate()
            self.assertIn('OnTimer1100:',editor.preview.toPlainText())
            change()
            with self.assertRaises(ValueError):editor.document()
            with patch('gui.event_timer_editor.QMessageBox.warning') as warning:editor.generate()
            warning.assert_called_once()
            self.assertEqual(editor.preview.toPlainText(),'')
            editor.close();editor.deleteLater()
        self.assertEqual(report,before)

    def test_manual_timer_adoption_requires_explicit_times_and_current_comparison(self):
        from copy import deepcopy
        from gui.event_timer_editor import EventTimerEditor
        from tests.support.event_trials import repeated_report
        panel = self.window.dialogue_panel.event_trials
        panel.window.setValue(2000)
        panel.report = report = repeated_report('effect')
        panel.report_key = panel.current_key()
        panel.show_trial_summary()
        before = deepcopy(report)
        with patch('gui.event_timer_editor.EventTimerEditor.exec', return_value=0) as opened:
            panel.adopt_timer()
        opened.assert_called_once()
        current = [True]
        editor = EventTimerEditor(report, 0, panel, is_current=lambda: current[0])
        self.assertEqual([field.text() for field in editor.times], ['', ''])
        with self.assertRaises(ValueError):
            editor.document()
        for field in editor.times:
            field.setText('100')
        with self.assertRaises(ValueError):
            editor.document()
        editor.confirmed.setChecked(True)
        editor.generate()
        self.assertEqual(editor.preview.toPlainText().count('OnTimer100:'), 1)
        self.assertIn('misceffect 9;', editor.preview.toPlainText())
        destination = Path(self.log_folder.name) / 'timer.json'
        with patch('gui.event_timer_editor.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            editor.save()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(saved['manual_times_ms'], [100, 100])
        self.assertEqual(saved['source_report']['trials'][0]['events'][1]['offset_ms'], 1000)
        self.assertFalse(saved['automatic_start_generated'])
        editor.times[1].setText('1100')
        self.assertEqual(editor.preview.toPlainText(), '')
        self.assertFalse(editor.confirmed.isChecked())
        editor.confirmed.setChecked(True)
        editor.generate()
        self.assertIn('OnTimer1100:', editor.preview.toPlainText())
        with patch('gui.event_timer_editor.QFileDialog.getOpenFileName', return_value=(str(destination), '')):
            editor.load()
        self.assertEqual([field.text() for field in editor.times], ['100', '100'])
        self.assertFalse(editor.confirmed.isChecked())
        self.assertEqual(editor.preview.toPlainText(), '')
        editor.confirmed.setChecked(True)
        original_document = editor.document()
        destination.write_text('{}', encoding='utf-8')
        with patch('gui.event_timer_editor.QFileDialog.getOpenFileName', return_value=(str(destination), '')), \
                patch('gui.event_timer_editor.QMessageBox.warning') as failed_load:
            editor.load()
        failed_load.assert_called_once()
        self.assertEqual(editor.document(), original_document)
        text_path = destination.with_suffix('.txt')
        with patch('gui.event_timer_editor.QFileDialog.getSaveFileName', return_value=(str(text_path), '')):
            editor.save(as_text=True)
        text = text_path.read_text(encoding='utf-8')
        evidence, code = text.split('\n', 1)
        self.assertEqual(json.loads(evidence[3:]), json.loads(json.dumps(original_document)))
        self.assertEqual(code, original_document['auriga'])
        old_bytes = text_path.read_bytes()
        with patch('gui.event_timer_editor.QFileDialog.getSaveFileName', return_value=(str(text_path), '')), \
                patch('gui.event_timer_editor.os.replace', side_effect=OSError('locked')), \
                patch('gui.event_timer_editor.QMessageBox.warning') as failed_save:
            editor.save(as_text=True)
        failed_save.assert_called_once()
        self.assertEqual(text_path.read_bytes(), old_bytes)
        def choose_stale_path(*args):
            current[0] = False
            return str(text_path), ''
        with patch('gui.event_timer_editor.QFileDialog.getSaveFileName', side_effect=choose_stale_path), \
                patch('gui.event_timer_editor.QMessageBox.warning') as stale_save:
            editor.save(as_text=True)
        stale_save.assert_called_once()
        self.assertEqual(text_path.read_bytes(), old_bytes)
        current[0] = False
        destination.write_text(json.dumps(saved), encoding='utf-8')
        with patch('gui.event_timer_editor.QFileDialog.getOpenFileName', return_value=(str(destination), '')), \
                patch('gui.event_timer_editor.QMessageBox.warning') as stale_load:
            editor.load()
        stale_load.assert_called_once()
        self.assertEqual([field.text() for field in editor.times], ['100', '100'])
        with patch('gui.event_timer_editor.QMessageBox.warning') as warning:
            editor.generate()
        warning.assert_called_once()
        self.assertEqual(editor.preview.toPlainText(), '')
        self.assertEqual(report, before)
        editor.close(); editor.deleteLater()
        panel.report = deepcopy(report)
        panel.report['trials'][0]['quality_flags'] = ['overlapping_windows']
        with patch('gui.event_trials.QMessageBox.warning') as warning:
            panel.adopt_timer()
        warning.assert_called_once()

    def test_instance_target_exclusion_retains_raw_recipient_and_partial_owner_is_rejected(self):
        from copy import deepcopy
        from PySide6.QtCore import QItemSelectionModel
        from tests.support.event_trials import instance_action_store
        fixture=instance_action_store()
        fixture.sessions[2].actions[0]['fields']['target']=deepcopy(fixture.sessions[1].actions[0]['fields']['target'])
        store=self.window.dialogues
        store.sessions=fixture.sessions;store.revision+=1
        panel=self.window.dialogue_panel.event_trials
        panel.anchor_mode.setCurrentIndex(panel.anchor_mode.findData('dialogue_start'))
        panel.include_actions.setChecked(True);panel.window.setValue(2000)
        def select():
            for index,row in enumerate(panel.rows):
                if row.get('anchor_type')=='dialogue_start':
                    panel.table.selectionModel().select(panel.table.model().index(index,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        select();panel.compute()
        panel.events.selectRow(1)
        self.assertIn('作用先表示は生の名前・MAP',panel.event_difference.toPlainText())
        panel.trials.selectRow(2)
        self.assertEqual(panel.current_review['excluded_counts'],{'target_different_map':1})
        self.assertIn('会話: Owner_eF3',panel.exclusions.item(0,1).text())
        self.assertIn('作用先: Target_cD2',panel.exclusions.item(0,1).text())
        self.assertIn('cD21@toy.gat',panel.exclusions.item(0,1).text())
        self.assertIn('cD21@toy.gat',panel.exclusions.item(0,1).toolTip())
        self.assertIn('別インスタンス',panel.exclusions.item(0,3).text())
        self.assertIn('target_different_map',panel.exclusions.item(0,3).text())
        self.assertEqual(panel.exclusions.item(0,3).toolTip(),'target_different_map')
        panel.exclusions.selectRow(0)
        with patch.object(panel,'on_source') as source:panel.jump_excluded_event()
        source.assert_called_once_with(315)
        for item in store.sessions:item.npc['name']='Owner_'
        store.revision+=1;panel.refresh();select()
        with patch('gui.event_trials.QMessageBox.warning') as warning:panel.compute()
        warning.assert_called_once()
        self.assertIn('省略',warning.call_args.args[2])
        self.assertIsNone(panel.report)
        self.assertEqual(panel.exclusions.rowCount(),0)

    def test_dialogue_actions_option_wait_exclusions_navigation_and_selection_reload(self):
        from PySide6.QtCore import QItemSelectionModel
        w=self.window
        w.add_packet(map_packet(connection='game',timestamp=0))
        w.add_packet(actor_packet(connection='game',timestamp=0))
        for start in (1,11):
            for pid,body,direction,offset in [(0x90,struct.pack('<IB',42,1),'SEND',0),
                (0xb4,struct.pack('<I',42)+b'hello\0','RECV',.1),
                (0x2f0,struct.pack('<II',0xaabbcc,2),'RECV',.2),
                (0xb5,struct.pack('<I',42),'RECV',.3),
                (0x2f0,struct.pack('<II',0xaabbcc,3),'RECV',.4),
                (0xb9,struct.pack('<I',42),'SEND',.5),
                (0xb6,struct.pack('<I',42),'RECV',.6),
                (0x146,struct.pack('<I',42),'SEND',.7)]:
                w.add_packet(packet(pid,body,direction=direction,flow='game',connection='game',timestamp=start+offset))
        source=Path(self.log_folder.name)/'source.jsonl'
        source.write_text(json.dumps(dict(kind='session_start',schema=1,record_payload=True))+'\n',encoding='utf-8')
        w.world_sources[0]=str(source)
        w.dialogues.action_dropped=2
        before=w.dialogues.snapshot()
        panel=w.dialogue_panel.event_trials
        panel.anchor_mode.setCurrentIndex(panel.anchor_mode.findData('dialogue_start'))
        self.assertEqual(len(panel.rows),2)
        self.assertTrue(panel.include_actions.isEnabled())
        panel.include_actions.setChecked(True)
        self.assertEqual(len(panel.rows),6)
        panel.window.setValue(2000)
        for index,row in enumerate(panel.rows):
            if row.get('anchor_type')=='dialogue_start':
                panel.table.selectionModel().select(panel.table.model().index(index,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        panel.compute()
        self.assertTrue(panel.report['include_dialogue_actions'])
        self.assertEqual(panel.report['action_dropped'],2)
        self.assertIn('会話アクションの未保存 2件',panel.note.text())
        self.assertEqual(panel.current_review['excluded_counts'],{'input_wait':1})
        self.assertIn('作用先: 未特定',panel.events.item(1,4).text())
        panel.exclusions.selectRow(0);panel.jump_excluded_event()
        self.assertEqual(w.selected_packet_index(),6)
        target=Path(self.log_folder.name)/'action-anchors.json'
        with patch('gui.event_trials.QFileDialog.getSaveFileName',return_value=(str(target),'')):panel.save_anchors()
        panel.include_actions.setChecked(False)
        self.assertIsNone(panel.report)
        self.assertEqual(panel.exclusions.rowCount(),0)
        panel.anchor_mode.setCurrentIndex(panel.anchor_mode.findData('presentation'))
        with patch('gui.event_trials.QFileDialog.getOpenFileName',return_value=(str(target),'')),patch('gui.event_trials.QMessageBox.warning') as warning:
            panel.load_anchors()
        warning.assert_not_called()
        self.assertEqual(panel.anchor_mode.currentData(),'dialogue_start')
        self.assertTrue(panel.include_actions.isChecked())
        self.assertEqual(len(panel.selected_indices()),2)
        panel.compute()
        self.assertEqual([len(trial['events']) for trial in panel.report['trials']],[2,2])
        report=panel.report
        selected=panel.selected_indices()
        document=json.loads(target.read_text(encoding='utf-8'))
        document['anchors'][0]['event_sha256']='0'*64
        document['comparison']={'mode':'map_arrival','include_actions':False}
        target.write_text(json.dumps(document),encoding='utf-8')
        with patch('gui.event_trials.QFileDialog.getOpenFileName',return_value=(str(target),'')),patch('gui.event_trials.QMessageBox.warning') as warning:
            panel.load_anchors()
        warning.assert_called_once()
        self.assertIs(panel.report,report)
        self.assertEqual(panel.selected_indices(),selected)
        self.assertEqual(panel.window.value(),2000)
        self.assertEqual(panel.anchor_mode.currentData(),'dialogue_start')
        self.assertTrue(panel.include_actions.isChecked())
        self.assertEqual(w.dialogues.snapshot(),before)

    def test_clock_exclusions_show_unavailable_offset_and_navigate_original_packets(self):
        from PySide6.QtCore import QItemSelectionModel
        w=self.window
        w.add_packet(map_packet(connection='game',timestamp=0))
        w.add_packet(actor_packet(connection='game',timestamp=0))
        for timestamp,value in [(1,7),(2,9),(11,7),(12,9),(21,7),(22,9)]:
            w.add_packet(packet(0xc0,struct.pack('<IB',42,value),flow='game',connection='game',timestamp=timestamp))
        w.dialogues.presentation_observations[1]['timestamp']=float('nan')
        w.dialogues.presentation_observations[3]['timestamp']=10.5
        panel=w.dialogue_panel.event_trials
        panel.refresh();panel.window.setValue(2000)
        selection=panel.table.selectionModel()
        for row in (0,2,4):
            selection.select(panel.table.model().index(row,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        panel.compute()
        self.assertEqual(panel.current_review['excluded_counts'],{'invalid_time':1})
        self.assertEqual(panel.exclusions.item(0,0).text(),'算出不可')
        self.assertEqual(panel.exclusions.item(0,3).text(),'時刻不正・経過時間を算出不可（invalid_time）')
        panel.exclusions.selectRow(0);panel.jump_excluded_event()
        self.assertEqual(w.selected_packet_index(),3)
        panel.trials.selectRow(1)
        self.assertEqual(panel.current_review['excluded_counts'],{'time_reversed':1})
        self.assertEqual(float(panel.exclusions.item(0,0).text()),-500)
        self.assertEqual(panel.exclusions.item(0,3).text(),'時刻が逆行（time_reversed）')
        panel.exclusions.selectRow(0);panel.jump_excluded_event()
        self.assertEqual(w.selected_packet_index(),5)
        self.assertFalse(panel.report['cause_confirmed'])
        self.assertFalse(panel.report['server_timer_confirmed'])
        panel.window.setValue(1000)
        self.assertEqual(panel.exclusions.rowCount(),0)
        self.assertIsNone(panel.current_review)

    def test_manual_event_anchors_compare_without_changing_code_or_accepting_stale_results(self):
        from PySide6.QtCore import QItemSelectionModel
        w = self.window
        w.add_packet(map_packet(connection='game', timestamp=0))
        w.add_packet(actor_packet(connection='game', timestamp=0))
        for time, value in ((1, 7), (2, 9), (11, 7), (12, 9), (21, 7), (22, 9)):
            w.add_packet(packet(0xc0, struct.pack('<IB', 42, value), flow='game', connection='game', timestamp=time))
        self.assertFalse(w.dialogues.sessions)
        source_path = Path(self.log_folder.name) / 'capture.jsonl'
        source_path.write_text(json.dumps(dict(kind='session_start', schema=1, record_payload=True)) + '\n', encoding='utf-8')
        w.dialogues.source_refs[0] = str(source_path)
        panel = w.dialogue_panel.event_trials
        panel.refresh()
        self.assertEqual(panel.table.rowCount(), 6)
        panel.window.setValue(2000)
        selection = panel.table.selectionModel()
        for row in (0, 2, 4):
            selection.select(panel.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        before = w.dialogues.snapshot()
        panel.compute()
        self.assertEqual(panel.report['status'], 'repeated_consistent')
        self.assertFalse(panel.report['cause_confirmed'])
        self.assertEqual(panel.timings.rowCount(), 1)
        self.assertEqual(panel.timings.item(0, 2).text(), '3')
        self.assertEqual(float(panel.timings.item(0, 4).text()), 1000)
        self.assertIn('反復一致', panel.timings.item(0, 7).text())
        self.assertEqual(panel.timing_samples.rowCount(), 3)
        panel.timing_samples.selectRow(2)
        panel.jump_timing_sample()
        self.assertEqual(w.table.currentRow(), 7)
        self.assertEqual(panel.trials.rowCount(), 3)
        self.assertEqual(panel.trials.item(0, 1).text(), '比較対象')
        panel.trials.selectRow(2)
        self.assertEqual(panel.events.rowCount(), 2)
        panel.events.selectRow(1)
        panel.jump_event()
        self.assertEqual(w.table.currentRow(), 7)
        selection.setCurrentIndex(panel.table.model().index(0, 0), QItemSelectionModel.NoUpdate)
        panel.jump()
        self.assertEqual(w.table.currentRow(), 2)
        destination = Path(self.log_folder.name) / 'trials.json'
        with patch('gui.event_trials.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertFalse(saved['coverage_verified'])
        self.assertEqual(len(saved['trials']), 3)
        self.assertEqual(w.dialogues.snapshot(), before)
        checkpoint = Path(self.log_folder.name) / 'selection.json'
        with patch('gui.event_trials.QFileDialog.getSaveFileName', return_value=(str(checkpoint), '')):
            panel.save_anchors()
        original_checkpoint = checkpoint.read_bytes()
        panel.window.setValue(1000)
        selection.clearSelection()
        with patch('gui.event_trials.QFileDialog.getOpenFileName', return_value=(str(checkpoint), '')):
            panel.load_anchors()
        self.assertEqual(panel.selected_indices(), [0, 2, 4])
        self.assertEqual(panel.window.value(), 2000)
        self.assertIsNone(panel.report)
        self.assertEqual(panel.timings.rowCount(), 0)
        panel.compute()
        current_report = panel.report
        changed = json.loads(original_checkpoint)
        changed['anchors'][0]['event_sha256'] = '0' * 64
        checkpoint.write_text(json.dumps(changed), encoding='utf-8')
        with patch('gui.event_trials.QFileDialog.getOpenFileName', return_value=(str(checkpoint), '')), \
             patch('gui.event_trials.QMessageBox.warning') as warning:
            panel.load_anchors()
        warning.assert_called_once()
        self.assertIs(panel.report, current_report)
        self.assertEqual(panel.selected_indices(), [0, 2, 4])
        self.assertEqual(panel.window.value(), 2000)
        panel.window.setValue(2500)
        self.assertIsNone(panel.report)
        panel.compute()
        w.add_packet(packet(0xc0, struct.pack('<IB', 42, 10), flow='game', connection='game', timestamp=22.5))
        with patch('gui.event_trials.QMessageBox.information') as information:
            panel.save()
        information.assert_called_once()
        panel.check_revision()
        self.assertIsNone(panel.report)
        self.assertEqual(panel.trials.rowCount(), 0)
        self.assertEqual(panel.events.rowCount(), 0)
        self.assertEqual(panel.timings.rowCount(), 0)
        self.assertEqual(panel.timing_samples.rowCount(), 0)
        panel.compute()
        self.assertIsNone(panel.report)
        self.assertIn('観測が更新', panel.note.text())
        panel.refresh()
        for row in (0, 2, 4):
            selection.select(panel.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        panel.compute()
        self.assertEqual(panel.report['status'], 'observed_difference')
        self.assertIn('追加観測', panel.trials.item(2, 6).text())
        self.assertEqual(panel.timings.rowCount(), 3)
        self.assertTrue(all(panel.timings.item(row, 7).text() == '比較不足' for row in range(3)))
        panel.timings.selectRow(2)
        self.assertEqual(panel.timing_samples.rowCount(), 1)
        panel.jump_timing_sample()
        self.assertEqual(w.table.currentRow(), len(w.events) - 1)
        panel.trials.selectRow(2)
        self.assertEqual(panel.events.rowCount(), 3)
        panel.events.selectRow(2)
        panel.jump_event()
        self.assertEqual(w.table.currentRow(), len(w.events) - 1)
        panel.window.setValue(60000)
        panel.compute()
        self.assertEqual(panel.report['status'], 'no_eligible_trials')
        self.assertTrue(all('観測窓が重複' in panel.trials.item(row, 1).text() for row in range(3)))
        self.assertEqual(panel.timings.rowCount(), 0)
        self.assertEqual(panel.timing_samples.rowCount(), 0)
        for time, value in ((31, 7), (33, 9)):
            w.add_packet(packet(0xc0, struct.pack('<IB', 42, value), flow='game', connection='game', timestamp=time))
        panel.refresh()
        panel.window.setValue(2500)
        for row in (0, 2, 4, 7):
            selection.select(panel.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        panel.compute()
        self.assertEqual(panel.timings.item(0, 2).text(), '3')
        self.assertEqual(float(panel.timings.item(0, 5).text()), 2000)
        self.assertIn('変動', panel.timings.item(0, 7).text())
        self.assertFalse(panel.report['server_timer_confirmed'])

    def test_comparison_uses_shared_timing_policy_preserves_evidence_and_invalidates_stale_results(self):
        w = self.window
        w.add_packet(map_packet(connection='game', timestamp=0))
        w.add_packet(actor_packet(connection='game', timestamp=0))
        actor = struct.pack('<I', 42)
        def add(pid, body=b'', timestamp=0, direction='RECV'):
            w.add_packet(packet(pid, body, direction, flow='game', connection='game', timestamp=timestamp))
        for start in (1, 11, 21):
            add(0x90, actor + b'\1', start, 'SEND')
            add(0xb4, actor + b'one\0', start + .05)
            add(0xb4, actor + b'two\0', start + 2.05)
            add(0xb6, actor, start + 2.06)
        # A ten-second player wait is not a fourth autonomous observation.
        add(0x90, actor + b'\1', 31, 'SEND')
        add(0xb4, actor + b'one\0', 31.05)
        add(0xb5, actor, 31.1)
        add(0xb9, actor, 41.1, 'SEND')
        add(0xb4, actor + b'two\0', 41.2)
        add(0xb6, actor, 41.21)
        source = Path(self.log_folder.name) / 'capture.jsonl'
        w.dialogues.source_refs[0] = str(source)
        panel = w.dialogue_panel.timing_comparison
        panel.set_conversation(w.dialogues.sessions[0])
        before = w.dialogues.snapshot()
        panel.compute()
        self.assertEqual(panel.table.rowCount(), 1)
        group = panel.report['summary']['groups'][0]
        self.assertEqual((group['count'], group['median_ms'], group['status']), (3, 2000, 'repeated_consistent'))
        self.assertEqual(panel.samples.rowCount(), 3)
        self.assertIn('入力待ち 1件', panel.note.text())
        self.assertIn('未応答の待機 4件', panel.note.text())
        self.assertEqual(panel.samples.item(0, 0).toolTip(), str(source))
        panel.jump('from_packet_index')
        self.assertEqual(w.table.currentRow(), group['samples'][0]['from_packet_index'])
        panel.samples.selectRow(2)
        panel.jump('to_packet_index')
        self.assertEqual(w.table.currentRow(), group['samples'][2]['to_packet_index'])
        destination = Path(self.log_folder.name) / 'comparison.json'
        with patch('gui.timing_comparison.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertFalse(saved['server_timer_confirmed'])
        self.assertEqual(saved['summary']['groups'][0]['count'], 3)
        self.assertEqual(w.dialogues.snapshot(), before)
        with patch('gui.timing_comparison.QFileDialog.getSaveFileName', return_value=(str(source), '')), \
             patch('gui.timing_comparison.QMessageBox.warning') as warning:
            panel.save()
        warning.assert_called_once()
        self.assertFalse(source.exists())
        add(0x90, actor + b'\1', 50, 'SEND')
        with patch('gui.timing_comparison.QMessageBox.information') as information:
            panel.save()
        information.assert_called_once()
        panel.jump('to_packet_index')
        self.assertIsNone(panel.report)
        self.assertEqual(panel.table.rowCount(), 0)
        panel.set_conversation(None)
        panel.compute()
        self.assertIn('マップ・名前・外見・XY', panel.note.text())
