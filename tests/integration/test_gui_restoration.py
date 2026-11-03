import json
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from tests.support.qt import install_offscreen_qt_message_filter
install_offscreen_qt_message_filter()
from tests.support.display import event
from tests.support.world import actor_packet, map_packet, name_packet
import struct



from tests.support.qt import WindowTestCase


class RestorationGuiTests(WindowTestCase):
    def test_dialogue_json_is_deferred_reused_and_tracks_selection_revision_and_merge(self):
        from tests.support.dialogue import layout_conversation
        from copy import deepcopy
        from dataclasses import asdict
        w=self.window;panel=w.dialogue_panel
        w.dialogues.sessions=[layout_conversation(identifier=1),layout_conversation(320,2,2)]
        w.dialogues.revision+=1
        before=deepcopy(w.dialogues.snapshot())
        with patch('gui.dialogues.asdict',wraps=asdict) as serialized:
            panel.refresh()
            self.assertEqual(panel.evidence.document().toPlainText(),'')
            self.assertEqual(panel.presentations.document().toPlainText(),'')
            self.assertEqual(serialized.call_count,0)
            evidence=json.loads(panel.evidence.toPlainText())
            self.assertEqual(evidence['conversation']['id'],1)
            panel.evidence.toPlainText();panel.refresh_selected()
            self.assertEqual(serialized.call_count,1)
            global_json=panel.presentations.toPlainText()
            updates=[];panel.presentations.textChanged.connect(lambda:updates.append(True))
            panel.selection.setCurrentIndex(1)
            self.assertEqual(panel.evidence.document().toPlainText(),'')
            self.assertEqual(json.loads(panel.evidence.toPlainText())['conversation']['id'],2)
            self.assertEqual(panel.presentations.toPlainText(),global_json)
            self.assertFalse(updates)
            panel.merge_checkbox.setChecked(True)
            self.assertIn('merged_group',json.loads(panel.evidence.toPlainText()))
            # Store.revision alone must not rematerialize presentations JSON (#85).
            before_calls=panel.presentations.factory_calls
            w.dialogues.revision+=1;panel.refresh()
            self.assertEqual(panel.presentations.factory_calls,before_calls)
            self.assertEqual(json.loads(panel.presentations.toPlainText())['observations'],[])
            self.assertEqual(panel.presentations.factory_calls,before_calls)
        self.assertEqual(w.dialogues.snapshot(),before)
        # A packet update can arrive before the regular GUI refresh timer.
        panel.merge_checkbox.setChecked(False)
        w.dialogues.sessions[1].steps[1]['fields']['text']='latest before refresh'
        w.dialogues.revision+=1
        evidence=json.loads(panel.evidence.toPlainText())
        self.assertEqual(evidence['conversation']['steps'][1]['fields']['text'],'latest before refresh')
        self.assertEqual(panel.revision,w.dialogues.revision)

    def test_deferred_json_materializes_when_shown_and_store_replacement_invalidates_merge(self):
        from gui.deferred_json import DeferredJsonView
        from reconstruction.dialogue import DialogueStore
        from tests.support.dialogue import layout_conversation
        view=DeferredJsonView();calls=[]
        try:
            view.set_document(1,lambda:calls.append(1) or {'value':1})
            self.assertFalse(calls)
            view.show();self.app.processEvents()
            self.assertEqual(json.loads(view.toPlainText()),{'value':1})
            self.assertEqual(calls,[1])
            view.set_document(2,lambda:{'value':2})
            self.assertEqual(json.loads(view.document().toPlainText()),{'value':2})
            view.clear();self.assertEqual(view.toPlainText(),'')
        finally:view.close()
        panel=self.window.dialogue_panel;old=panel.store
        old.sessions=[layout_conversation()];old.revision+=1;panel.refresh()
        first=panel.merged_report()
        replacement=DialogueStore();replacement.revision=old.revision
        replacement.sessions=[layout_conversation(identifier=9)]
        panel.store=replacement;panel.refresh()
        self.assertEqual(panel.selected().id,9)
        self.assertIsNot(panel.merged_report(),first)
        self.assertEqual(json.loads(panel.evidence.toPlainText())['conversation']['id'],9)

    def test_async_merge_discards_stale_worker_results(self):
        from reconstruction.branches import build_merged
        from reconstruction.dialogue import DialogueStore
        from tests.support.dialogue import layout_conversation
        panel=self.window.dialogue_panel
        panel.merge_async_threshold=0
        panel.merge_checkbox.setChecked(True)
        store=DialogueStore()
        store.sessions=[layout_conversation(identifier=1),layout_conversation(identifier=2)]
        store.revision=1
        panel.store=store
        panel._refreshed_store=store
        panel.revision=store.revision
        stale_key=panel._merge_cache_key()
        panel._merge_pending_key=stale_key
        stale_report=build_merged(panel._merge_inputs(), touch_inferences=[])
        store.revision+=1
        store.sessions.append(layout_conversation(identifier=3))
        panel.revision=store.revision
        panel._merge_worker_finished(stale_key, stale_report)
        self.assertIsNone(panel._merge_report)
        self.assertNotEqual(panel._merge_key, stale_key)
        current=panel._merge_cache_key()
        panel._merge_pending_key=current
        fresh=build_merged(panel._merge_inputs(), touch_inferences=[])
        panel._merge_worker_finished(current, fresh)
        self.assertIs(panel._merge_report, fresh)
        self.assertEqual(panel._merge_key, current)
        self.assertEqual(panel._merge_key[1], 2)

    def test_reference_browser_pages_and_filters_without_changing_observations(self):
        from copy import deepcopy
        w=self.window;browser=w.reference_browser
        before=deepcopy((w.players.snapshot(),w.world.snapshot(),w.dialogues.snapshot()))
        browser.kind.setCurrentIndex(browser.kind.findData('maps'))
        browser.map_query.setText('prontera.gat')
        self.assertEqual(browser.table.rowCount(),1)
        self.assertEqual(browser.table.item(0,0).text(),'prontera')
        self.assertTrue(browser.table.item(0,1).text())
        self.assertTrue(browser.table.item(0,2).text())
        browser.map_query.clear();browser.kind.setCurrentIndex(browser.kind.findData('quests'))
        browser.query.setText('12059')
        self.assertEqual(browser.table.rowCount(),1)
        self.assertIn('名称候補',browser.table.item(0,1).text())
        browser.query.clear();browser.kind.setCurrentIndex(browser.kind.findData('mobs'))
        self.assertEqual(browser.table.rowCount(),100)
        browser.next.click();self.assertEqual(browser.offset,100)
        browser.previous.click();self.assertEqual(browser.offset,0)
        browser.map_query.setText('abbey01.rsw')
        self.assertTrue(browser.table.rowCount())
        self.assertTrue(all(browser.table.item(i,0).text()=='abbey01' for i in range(browser.table.rowCount())))
        browser.table.setCurrentCell(0,0)
        self.assertIn(w.navigation['_sha256'],browser.details.toPlainText())
        self.assertEqual((w.players.snapshot(),w.world.snapshot(),w.dialogues.snapshot()),before)

    def test_item_command_reference_names_preserve_evidence_and_generated_code(self):
        from copy import deepcopy
        from tests.unit.test_script_commands import ScriptCommandTests
        from tests.support.player import pickup,packet
        from reconstruction.auriga import AurigaRenderer
        helper=ScriptCommandTests()
        _,store,consume=helper.setup_store()
        consume(pickup(index=2,item_id=501,amount=3))
        consume(packet(0xaf,struct.pack('<HH',2,1)))
        consume(pickup(index=3,item_id=2147483647,amount=1))
        from dataclasses import replace
        equipment=pickup(index=4,item_id=1101,amount=1)
        raw=bytearray(equipment.raw);raw[68]=7
        consume(replace(equipment,raw=bytes(raw)))
        helper.close(consume)
        before=deepcopy(store.snapshot())
        code=AurigaRenderer().render(store.sessions[0])
        panel=self.window.dialogue_panel
        panel.store=store
        panel.refresh()
        references=[panel.timeline.item(i,7).text() for i in range(panel.timeline.rowCount())]
        self.assertTrue(any('ID=501 / 数量=3 / 赤ポーション' in value for value in references))
        self.assertTrue(any('ID=501 / 数量=1 / 赤ポーション' in value for value in references))
        self.assertTrue(any('ID=2147483647' in value and '未登録' in value for value in references))
        self.assertEqual(store.snapshot(),before)
        self.assertEqual(AurigaRenderer().render(store.sessions[0]),code)
        self.assertIn('getitem 501,3;',code)
        self.assertIn('delitem 501,1;',code)
        self.assertTrue(any('ID=1101 / 数量=1 /' in value for value in references))
        self.assertIn('getitem2 1101,1,1,7,0,0,0,0,0;',code)

    def test_shop_reference_names_keep_client_ids_prices_models_and_generated_code(self):
        from copy import deepcopy
        from tests.unit.test_shop_export import observe_shop
        from reconstruction.shop_export import ShopRenderer
        w=self.window
        record,conversation=observe_shop(False)
        w.shops.records=[record];w.shops.revision+=1
        before=deepcopy(w.shops.snapshot())
        code=ShopRenderer().render(record,'shop',item_ids_confirmed=True,conversation=conversation)
        w.shop_panel.refresh()
        self.assertEqual(w.shop_panel.table.item(0,0).text(),'501')
        self.assertEqual(w.shop_panel.table.item(0,1).text(),'100')
        self.assertEqual(w.shop_panel.table.item(0,2).text(),'76')
        self.assertEqual(w.shop_panel.table.item(0,6).text(),'赤ポーション')
        self.assertIn('確定しません',w.shop_panel.table.item(0,6).toolTip())
        self.assertIs(w.shop_panel.names,w.player_panel.names)
        self.assertEqual(w.shops.snapshot(),before)
        self.assertEqual(ShopRenderer().render(record,'shop',item_ids_confirmed=True,conversation=conversation),code)

    def test_modern_equipment_identification_flag_does_not_use_grade_or_favorite_bit(self):
        from tests.support.player import packet,listing
        from dataclasses import replace
        w=self.window
        w.add_packet(packet(0xb08,b'\0'))
        event=listing(0xb39,items=((2,501,1),(3,502,1)))
        raw=bytearray(event.raw)
        raw[5+66]=9;raw[5+67]=5
        raw[5+68+66]=1;raw[5+68+67]=4
        w.add_packet(replace(event,raw=bytes(raw)))
        w.add_packet(packet(0xb0b,b'\0\0'));w.refresh_entity_views()
        self.assertEqual(w.player_panel.items.item(0,4).text(),'鑑定済')
        self.assertEqual(w.player_panel.items.item(1,4).text(),'未鑑定')
        self.assertEqual(w.players.states[(0,'game')].items[2]['inventory_flags'],5)
        self.assertEqual(w.players.states[(0,'game')].items[3]['inventory_flags'],4)

    def test_inventory_reference_name_and_observed_identification_are_separate(self):
        from tests.support.player import packet,listing
        from dataclasses import replace
        w=self.window
        w.add_packet(packet(0xb08,b'\0'))
        event=listing();raw=bytearray(event.raw);raw[5+33]=2
        w.add_packet(replace(event,raw=bytes(raw)))
        w.add_packet(packet(0xb0b,b'\0\0'));w.refresh_entity_views()
        panel=w.player_panel
        self.assertEqual(panel.items.item(0,3).text(),'赤ポーション')
        self.assertEqual(panel.items.item(0,4).text(),'未鑑定')
        w.add_packet(packet(0x179,struct.pack('<HB',2,0)));w.refresh_entity_views()
        self.assertEqual(panel.items.item(0,4).text(),'鑑定済')
        self.assertEqual(panel.items.item(0,2).text(),'10')
        self.assertEqual(panel.items.item(0,3).text(),'赤ポーション')
        self.assertNotIn('item_unidentified',w.client_names['tables'])

    def test_client_labels_show_inventory_map_and_quest_without_changing_models_or_commands(self):
        from copy import deepcopy
        from tests.support.player import packet as player_packet,listing
        from tests.support.dialogue import packet
        from tests.unit.test_quest_observations import addition
        from dataclasses import replace
        w=self.window
        for event in (player_packet(0x91,b'prontera.gat'.ljust(16,b'\0')+struct.pack('<HH',10,20)),
                      player_packet(0xb08,b'\0'),listing(),player_packet(0xb0b,b'\0\0')):
            w.add_packet(event)
        for event in (packet(0x90,struct.pack('<IB',42,1),'SEND'),
                      replace(addition(),raw=addition().raw[:2]+struct.pack('<I',2063)+addition().raw[6:]),
                      packet(0xb6,struct.pack('<I',42))):
            w.add_packet(event)
        before=deepcopy((w.players.snapshot(),w.dialogues.snapshot()))
        w.refresh_entity_views()
        self.assertIn('prontera.gat',w.player_panel.summary.text())
        self.assertIn('プロンテラ',w.player_panel.summary.text())
        self.assertEqual(w.player_panel.items.item(0,1).text(),'501')
        self.assertEqual(w.player_panel.items.item(0,2).text(),'10')
        self.assertEqual(w.player_panel.items.item(0,3).text(),'赤ポーション')
        self.assertIn('識別状態',w.player_panel.items.item(0,3).toolTip())
        panel=w.dialogue_panel
        self.assertIn('setquest 2063;',panel.code.toPlainText())
        self.assertNotIn('checkquest(',panel.code.toPlainText())
        references=[panel.timeline.item(i,7).text() for i in range(panel.timeline.rowCount())]
        self.assertTrue(any('ID=2063' in value and '運命のカラス' in value for value in references))
        self.assertEqual((w.players.snapshot(),w.dialogues.snapshot()),before)
        self.assertIs(w.player_panel.names,panel.names)

    def test_wait_layout_timeout_merges_into_answered_code_and_bulk_export_once(self):
        from copy import deepcopy
        from tests.unit.test_timeout_merging import trial
        layouts=((0xba2,struct.pack('<II',180,280)),(0xbb5,struct.pack('<II',10,20)),(0xba1,b'\x01'))
        w=self.window
        w.dialogues.sessions=[trial(layouts=layouts),trial(complete=True,identifier=2,layouts=layouts)]
        w.dialogues.revision+=1
        before=deepcopy(w.dialogues.snapshot())
        w.refresh_entity_views()
        panel=w.dialogue_panel
        panel.selection.setCurrentIndex(0)
        self.assertIn('タイムアウト疑い',panel.code.toPlainText())
        self.assertNotIn('messize',panel.code.toPlainText())
        panel.merge_checkbox.setChecked(True)
        self.assertIn('未応答終了の前方一致 1件',panel.merge_status.text())
        self.assertIn('mes "continued";',panel.code.toPlainText())
        evidence=json.loads(panel.evidence.toPlainText())
        normalization=evidence['merged_group']['timeout_normalizations'][0]
        self.assertEqual(normalization['matched_wait_layout_observations'],3)
        for command in ('messize 180,280;','mespos 10,20;','mesalign 1;'):
            self.assertEqual(panel.code.toPlainText().count(command),1)
        destination=Path(self.log_folder.name)/'waiting-layout-merged.json'
        with patch('gui.main_window.QFileDialog.getSaveFileName',return_value=(str(destination),'')):
            w.save_all_npcs()
        report=json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(len(report['entries']),1)
        self.assertEqual(report['auriga'].count('messize 180,280;'),1)
        self.assertNotIn('close2;',report['auriga'])
        self.assertEqual(w.dialogues.snapshot(),before)

    def test_background_all_npc_layout_export_keeps_state_before_save_dialog_changes(self):
        from tests.support.dialogue import layout_conversation
        w=self.window
        for suffix in ('json','txt'):
            with self.subTest(suffix=suffix):
                w.dialogues.sessions=[layout_conversation(280 if index%2 else 320,
                    1 if index%2 else 2,index+1) for index in range(51)]
                w.dialogues.revision+=1
                w.dialogue_panel.merge_checkbox.setChecked(True)
                destination=Path(self.log_folder.name)/f'background-layouts.{suffix}'
                def choose(*args):
                    for item in w.dialogues.sessions:item.actions[0]['fields']['width']=999
                    return str(destination),''
                with patch('gui.main_window.QFileDialog.getSaveFileName',side_effect=choose):
                    w.export_all_npcs_action.trigger()
                self.wait_display_export()
                text=destination.read_text(encoding='utf-8')
                if suffix=='json':
                    report=json.loads(text)
                    self.assertTrue(report['dialogue_merged'])
                    self.assertFalse(report['excluded'])
                    text=report['auriga']
                self.assertIn('messize 180,280;',text)
                self.assertIn('messize 180,320;',text)
                self.assertIn('mespos 10,20;',text)
                self.assertIn('mesalign 1;',text)
                self.assertIn('mesalign 2;',text)
                self.assertNotIn('messize 180,999;',text)

    def test_all_npc_menu_exports_layout_commands_in_both_formats_and_merge_modes(self):
        from copy import deepcopy
        from tests.support.dialogue import layout_conversation
        w=self.window
        w.dialogues.sessions=[layout_conversation(),layout_conversation(320,2,2)]
        w.dialogues.revision+=1
        before=deepcopy(w.dialogues.snapshot())
        for merge in (False,True):
            w.dialogue_panel.merge_checkbox.setChecked(merge)
            outputs={}
            for suffix in ('json','txt'):
                destination=Path(self.log_folder.name)/f'layouts-{merge}.{suffix}'
                with patch('gui.main_window.QFileDialog.getSaveFileName',return_value=(str(destination),'')):
                    w.export_all_npcs_action.trigger()
                text=destination.read_text(encoding='utf-8')
                if suffix=='json':
                    report=json.loads(text)
                    self.assertEqual(report['dialogue_merged'],merge)
                    self.assertFalse(report['excluded'])
                    text=report['auriga']
                outputs[suffix]=text
                for command in ('messize 180,280;','messize 180,320;',
                                'mespos 10,20;','mesalign 1;','mesalign 2;'):
                    self.assertIn(command,text)
            self.assertEqual(outputs['json'],outputs['txt'])
        self.assertEqual(w.dialogues.snapshot(),before)

    def test_dialogue_layout_observations_keep_values_and_generate_commands(self):
        from tests.support.dialogue import packet
        w=self.window
        for event in (packet(0x90,struct.pack('<IB',42,1),'SEND'),
                      packet(0xb4,struct.pack('<I',42)+b'hello\0'),
                      packet(0xba2,struct.pack('<II',300,400)),
                      packet(0xbb5,struct.pack('<II',100,200)),packet(0xba1,b'\x02')):
            w.add_packet(event)
        w.refresh_entity_views()
        panel=w.dialogue_panel
        rows=json.loads(panel.presentations.toPlainText())['observations']
        self.assertEqual([row['kind'] for row in rows],
                         ['dialogue_size','dialogue_position','dialogue_alignment'])
        self.assertTrue(all(row['conversation_actor_id']==42 and row['actor_id'] is None for row in rows))
        self.assertEqual(rows[0]['fields'],{'height':300,'width':400})
        self.assertEqual(len(w.dialogues.sessions[0].steps),2)
        for command in ('messize 300,400;','mespos 100,200;','mesalign 2;'):
            self.assertIn(command,panel.code.toPlainText())
        trials=panel.event_trials
        trials.refresh()
        for index in range(3):
            trials.table.selectRow(index)
            self.assertIn('会話表示: 対象ID未記録',trials.table.item(index,3).text())
            self.assertIn('会話表示設定',trials.speech_note.text())
            self.assertFalse(trials.speech_source.isEnabled())

    def test_mapcell_has_target_description_without_creating_npc_conversation(self):
        from tests.support.world import packet
        w=self.window
        w.add_packet(map_packet('test.gat'))
        w.add_packet(packet(0x192,struct.pack('<HHH',100,200,1)+b'test.gat'.ljust(16,b'\0')))
        w.refresh_entity_views()
        self.assertFalse(w.dialogues.sessions)
        row=w.dialogues.snapshot()['presentation_observations'][0]
        self.assertEqual(row['map_context']['map_name'],'test.gat')
        panel=w.dialogue_panel.event_trials
        panel.refresh()
        panel.table.selectRow(0)
        self.assertIn('セル: test.gat (100,200)',panel.table.item(0,3).text())
        self.assertIn('呼出元NPC',panel.speech_note.text())
        self.assertFalse(panel.speech_source.isEnabled())
        self.assertEqual(row['fields']['cell_type'],1)

    def test_progress_protocol_diagnostics_are_visible_without_new_dialogue_steps(self):
        from tests.support.dialogue import packet
        w = self.window
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                      packet(0x2f0, struct.pack('<II', 0x123456, 7)),
                      packet(0x2f1, direction='SEND'), packet(0x2f2)):
            w.add_packet(event)
        w.refresh_entity_views()
        panel = w.dialogue_panel
        report = json.loads(panel.presentations.toPlainText())['progress_observations']
        self.assertEqual([r['kind'] for r in report['observations']],
                         ['progress_start', 'progress_client_report', 'progress_abort'])
        self.assertFalse(report['success_inferred'])
        self.assertIn('progressbar 7,0x123456;', panel.code.toPlainText())
        self.assertFalse(any(step['packet_id'] in (0x2f1, 0x2f2) for step in w.dialogues.sessions[0].steps))

    def test_npc_waitingroom_is_oninit_and_hidden_only_from_observation_log(self):
        from dataclasses import replace
        from tests.support.dialogue import packet
        from reconstruction.npc_bundle import build_npc_bundle
        w=self.window
        def room(actor):
            body=struct.pack('<IIHHB',actor,700,0,0,1)+b'Queue\0'
            return replace(packet(0xd7),raw=struct.pack('<HH',0xd7,len(body)+4)+body)
        for event in (map_packet(),actor_packet(name='Guide')):
            w.add_packet(event)
        w.add_packet(replace(room(42),connection='flow-a',flow_id=None))
        self.assertNotIn('waitingroom ',w.display_log.toPlainText())
        self.assertEqual(w.events[-1].packet_id,0xd7)
        bundle=build_npc_bundle(w.world.snapshot('NPC')['entities'],[])
        self.assertIn('OnInit:',bundle['auriga'])
        self.assertIn('waitingroom "Queue",0;',bundle['auriga'])
        w.add_packet(replace(room(888),connection='flow-a',flow_id=None))
        self.assertIn('waitingroom ',w.display_log.toPlainText())

    def test_conversation_progress_action_has_code_timeline_and_source_jump(self):
        from tests.support.dialogue import packet
        w = self.window
        for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                      packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                      packet(0x2f0, struct.pack('<II', 0x123456, 7)),
                      packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(event)
        w.refresh_entity_views()
        panel = w.dialogue_panel
        self.assertIn('progressbar 7,0x123456;', panel.code.toPlainText())
        labels = [panel.timeline.item(i, 4).text() for i in range(panel.timeline.rowCount())]
        panel.timeline.selectRow(labels.index('会話中プログレスバー'))
        panel.jump()
        self.assertEqual(w.table.currentRow(), 2)

    def test_full_placed_npc_menu_exports_decorations_dialogues_and_both_shop_forms_without_empty_init(self):
        from copy import deepcopy
        from reconstruction.world import Entity
        from tests.unit.test_shop_export import observe_shop
        w = self.window
        direct, _ = observe_shop(False)
        direct['conversation_id'] = None
        direct['npc']['name'] = 'Direct'
        linked, dialogue = observe_shop(True)
        w.dialogues.sessions = [dialogue]
        w.dialogues.revision += 1
        w.shops.records = [direct, linked]
        npc = Entity(0, 'half', 1, 99, 1, 'NPC', 6, 'test.gat', 1, 1,
                     name='Decoration', class_id=45, x=30, y=40, direction=0, group_id=0, title='  ',
                     metadata_evidence={'group_id': {}, 'title': {}})
        w.world.entities[npc.key] = npc
        before = deepcopy((w.dialogues.snapshot(), w.shops.snapshot(), w.world.snapshot()))
        self.assertIn('配置付きNPCコードを全件出力', w.export_all_npcs_action.text())
        for merge in (False, True):
            w.dialogue_panel.merge_checkbox.setChecked(merge)
            destination = Path(self.log_folder.name) / f'full-npcs-{merge}.json'
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
                w.export_all_npcs_action.trigger()
            report = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(report['dialogue_merged'], merge)
            self.assertEqual(len(report['entries']), 3)
            self.assertIn('\tscript\tDecoration', report['auriga'])
            self.assertIn('\tshop\tDirect', report['auriga'])
            self.assertIn('callshop "test.gat#callshop', report['auriga'])
            self.assertNotIn('OnInit:', report['auriga'])
            self.assertFalse(report['excluded'])
        self.assertEqual((w.dialogues.snapshot(), w.shops.snapshot(), w.world.snapshot()), before)

    def test_timeout_merge_with_matching_resources_uses_single_quest_command_and_keeps_original_states(self):
        from copy import deepcopy
        from tests.unit.test_timeout_merging import resource_trial
        w = self.window
        w.dialogues.sessions = [resource_trial(), resource_trial(True, 2)]
        w.dialogues.revision += 1
        before = deepcopy(w.dialogues.snapshot())
        w.refresh_entity_views()
        panel = w.dialogue_panel
        panel.selection.setCurrentIndex(0)
        panel.merge_checkbox.setChecked(True)
        self.assertIn('未応答終了の前方一致 1件', panel.merge_status.text())
        self.assertEqual(panel.code.toPlainText().count('setquest 12345;'), 1)
        self.assertIn('mes "continued";', panel.code.toPlainText())
        evidence = json.loads(panel.evidence.toPlainText())
        self.assertEqual(evidence['merged_group']['timeout_normalizations'][0]['matched_resource_observations'], 3)
        self.assertEqual(w.dialogues.snapshot(), before)

    def test_timeout_observation_selects_unified_continuation_in_merge_mode_and_bulk_export(self):
        from copy import deepcopy
        from tests.unit.test_timeout_merging import trial
        w = self.window
        partial, full = trial(), trial(complete=True, identifier=2)
        w.dialogues.sessions = [partial, full]
        w.dialogues.revision += 1
        before = deepcopy(w.dialogues.snapshot())
        w.refresh_entity_views()
        panel = w.dialogue_panel
        panel.selection.setCurrentIndex(0)
        self.assertIn('タイムアウト疑い', panel.code.toPlainText())
        panel.merge_checkbox.setChecked(True)
        self.assertIn('未応答終了の前方一致 1件', panel.merge_status.text())
        self.assertIn('mes "continued";', panel.code.toPlainText())
        self.assertNotIn('ここで終了しclose2', panel.code.toPlainText())
        self.assertEqual(panel.review_table.rowCount(), 0)
        destination = Path(self.log_folder.name) / 'timeout-merged.json'
        with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            w.save_all_npcs()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(len(saved['entries']), 1)
        self.assertEqual(saved['entries'][0]['rendered_paths'], 1)
        panel.merge_checkbox.setChecked(False)
        self.assertIn('タイムアウト疑い', panel.code.toPlainText())
        self.assertEqual(w.dialogues.snapshot(), before)

    def test_late_reply_after_timeout_is_timeline_evidence_and_does_not_restart_dialogue(self):
        from tests.support.dialogue import packet
        w = self.window
        for item in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'), packet(0xb5, struct.pack('<I', 42)),
                     packet(0xb6, struct.pack('<I', 42)), packet(0x146, struct.pack('<I', 42), 'SEND'),
                     packet(0xb9, struct.pack('<I', 42), 'SEND')):
            w.add_packet(item)
        w.refresh_entity_views()
        self.assertEqual(w.dialogues.issue_count, 0)
        self.assertEqual(len(w.dialogues.sessions), 1)
        self.assertIn('遅延応答候補 1件', w.dialogue_panel.code.toPlainText())
        self.assertNotIn('close2;', w.dialogue_panel.code.toPlainText())
        labels = [w.dialogue_panel.timeline.item(i, 4).text() for i in range(w.dialogue_panel.timeline.rowCount())]
        row = labels.index('終了後のnext応答候補')
        w.dialogue_panel.timeline.selectRow(row)
        w.dialogue_panel.jump()
        self.assertEqual(w.table.currentRow(), 4)

    def test_player_repeat_reference_reports_presence_differences_without_changing_code(self):
        from copy import deepcopy
        from tests.support.event_trials import player_notification_trial
        panel=self.window.dialogue_panel.external_presentations
        contributions=[];rows=[]
        for session,text in ((1,'one'),(2,'two'),(3,None)):
            contribution,notices=player_notification_trial(session,text)
            contributions.append(contribution);rows+=notices
        partial,_=player_notification_trial(4,None)
        partial['conversation']['steps'].pop()
        partial['conversation']['steps'][-1].pop('reply')
        contributions.append(partial)
        group={'contributions':contributions};before=deepcopy((group,rows))
        panel.set_conversation(None,group,{s:f'capture-{s}.jsonl' for s in (1,2,3)},rows)
        self.assertIn('有無・本文・文脈の差分 1経路',panel.caption.text())
        self.assertIn('本人通知比較の対象外 1観測',panel.caption.text())
        self.assertEqual(panel.table.rowCount(),2)
        panel.table.selectRow(0)
        evidence=json.loads(panel.detail.toPlainText())
        self.assertEqual(evidence['actor_id'],9001)
        report=evidence['player_notification_repeat_review']
        self.assertEqual(report['groups'][0]['observations'][2]['notification_count'],0)
        self.assertFalse(report['command_generation'])
        with patch.object(panel,'on_source') as source:panel.jump('packet_index')
        source.assert_called_once_with(115)
        self.assertEqual((group,rows),before)
        panel.player_review=dict(panel.player_review,display_limit_test='x'*200001)
        panel.show_selected()
        self.assertIn('表示上限',panel.detail.toPlainText())
        self.assertLess(len(panel.detail.toPlainText()),201000)
        self.assertEqual(len(panel.player_review['display_limit_test']),200001)


    def test_merged_player_notification_sources_duplicates_and_remapped_navigation(self):
        from copy import deepcopy
        panel=self.window.dialogue_panel.external_presentations
        contributions=[];rows=[];sources={}
        for session in (1,2,3):
            sources[session]=f'capture-{session}.jsonl'
            item=dict(capture_session=session,flow_id=f'flow-{session}',id=1,actor_id=42,
                steps=[dict(packet_index=session*100+4)],external_presentations=[])
            contributions.append(dict(conversation=item,source_ref=sources[session]))
            rows.append(dict(kind='overhead',fields={'text':'notice'},capture_session=session,
                flow_id=item['flow_id'],conversation_id=1,conversation_actor_id=42,actor_id=9000,
                entity_kind='PLAYER',association_basis='active_dialogue_same_flow_player_notification',
                after_step_index=0,packet_index=session*100+5,npc={},context='during_dialogue'))
        group=dict(contributions=contributions+[deepcopy(contributions[0]),dict(contributions[0],source_ref='foreign.jsonl')])
        inputs=deepcopy((group,rows))
        panel.set_conversation(None,group,sources,rows+[deepcopy(rows[0])])
        self.assertEqual(len(panel.rows),3)
        self.assertIn('出典不一致の寄与 1件',panel.caption.text())
        for number,session in enumerate((1,2,3)):
            panel.table.selectRow(number)
            self.assertEqual(panel.table.item(number,1).toolTip(),sources[session])
            with patch.object(panel,'on_source') as navigate:
                panel.jump('packet_index');panel.jump('anchor_packet_index')
            self.assertEqual([call.args[0] for call in navigate.call_args_list],[session*100+5,session*100+4])
        self.assertEqual((group,rows),inputs)
        mapping={1:9,2:4,3:1}
        new_group=deepcopy(dict(contributions=contributions));new_rows=deepcopy(rows)
        for contribution in new_group['contributions']:
            item=contribution['conversation'];item['capture_session']=mapping[item['capture_session']]
            item['steps'][0]['packet_index']+=10000
        for row in new_rows:row['capture_session']=mapping[row['capture_session']];row['packet_index']+=10000
        current=[True]
        panel.set_conversation(None,new_group,{mapping[k]:v for k,v in sources.items()},new_rows,is_current=lambda:current[0])
        self.assertEqual([row['capture_session'] for row in panel.rows],[1,4,9])
        panel.table.selectRow(0)
        with patch.object(panel,'on_source') as navigate:panel.jump('packet_index')
        navigate.assert_called_once_with(10305)
        # Same Packet with changed content is retained rather than silently deduplicated.
        changed=deepcopy(new_rows[0]);changed['fields']['text']='different'
        panel.set_conversation(None,new_group,{mapping[k]:v for k,v in sources.items()},new_rows+[changed],is_current=lambda:current[0])
        self.assertEqual(len(panel.rows),4)
        panel.table.selectRow(0);current[0]=False
        with patch.object(panel,'on_source') as navigate:panel.jump('anchor_packet_index')
        navigate.assert_not_called()
        self.assertEqual(panel.table.rowCount(),0)
        self.assertFalse(panel.event_button.isEnabled())
        self.assertIn('更新されています',panel.caption.text())

    def test_self_player_overhead_context_and_source_are_visible_without_code_generation(self):
        from dataclasses import replace
        from tests.support.dialogue import packet,overhead_event
        w=self.window
        events=[map_packet('test.gat'),packet(0x283,struct.pack('<I',9000)),actor_packet(name='Speaker'),
            packet(0x90,struct.pack('<IB',42,1),'SEND'),packet(0xb4,struct.pack('<I',42)+b'hello\0'),
            overhead_event(actor=9000,text='player during'),packet(0xb5,struct.pack('<I',42)),
            overhead_event(actor=9000,text='player waiting'),packet(0xb9,struct.pack('<I',42),'SEND'),
            packet(0xb6,struct.pack('<I',42)),packet(0x146,struct.pack('<I',42),'SEND')]
        for event in events:w.add_packet(replace(event,connection='game',flow_id='game'))
        w.refresh_entity_views()
        panel=w.dialogue_panel.external_presentations
        self.assertEqual(panel.table.rowCount(),2)
        self.assertIn('本人宛て関連通知 2件',panel.caption.text())
        self.assertIn('本人プレイヤー',panel.table.item(0,3).text())
        self.assertIn('会話中',panel.table.item(0,2).text())
        self.assertIn('入力待ち中',panel.table.item(1,2).text())
        panel.table.selectRow(0);panel.jump('packet_index')
        self.assertEqual(w.selected_packet_index(),5)
        panel.jump('anchor_packet_index');self.assertEqual(w.selected_packet_index(),4)
        self.assertNotIn('showmessage',w.dialogue_panel.code.toPlainText())
        self.assertEqual(len(w.dialogues.sessions),1)
        timeline=w.dialogues.snapshot()['timelines'][0]
        notifications=[row for row in timeline['rows'] if row.get('track')=='player_notification']
        self.assertEqual(len(notifications),2)
        self.assertTrue(all(not row['candidate'] and row['actor_id']==9000 for row in notifications))
        rows=[i for i in range(w.dialogue_panel.timeline.rowCount()) if '対象PLAYER 9000' in w.dialogue_panel.timeline.item(i,7).text()]
        self.assertEqual(len(rows),2)
        self.assertIn('player during',w.dialogue_panel.timeline.item(rows[0],7).text())
        self.assertEqual(w.dialogue_panel.timeline.item(rows[0],2).text(),'—')
        self.assertIn('観測専用',w.dialogue_panel.timing_caption.text())
        w.dialogue_panel.timeline.selectRow(rows[0]);w.dialogue_panel.jump()
        self.assertEqual(w.selected_packet_index(),5)
        revision=w.dialogues.revision
        w.dialogues.source_refs[0]='changed-source.jsonl'
        with patch.object(panel,'on_source') as navigate:panel.jump('packet_index')
        navigate.assert_not_called()
        self.assertEqual(w.dialogues.revision,revision)
        self.assertFalse(panel.event_button.isEnabled())
        self.assertEqual(panel.table.rowCount(),0)


    def test_touch_only_warp_explains_missing_click_and_provisional_walk_range(self):
        from reconstruction.dialogue import Conversation
        from reconstruction.touch import context
        from reconstruction.timing import build_timeline
        from tests.support.branches import NPC
        npc=dict(NPC)
        npc['touch']=context(npc,dict(map_name=npc['map_name'],x=npc['x'],y=npc['y'],
            position_basis='observed_walk_destination',packet_index=5),7)
        item=Conversation(1,0,'flow',42,2,False,status='map_changed',npc=npc,
            termination=dict(timestamp=2,packet_index=7,packet_id=0x92,direction='RECV',connection='flow',source='TEST',
                fields=dict(map_name='target.gat',x=86,y=58,source_map_name=npc['map_name'])))
        w=self.window;w.dialogues.sessions=[item];w.dialogues.revision+=1
        w.refresh_entity_views()
        panel=w.dialogue_panel
        self.assertIn('OnTouch候補・起因未確定',panel.timing_caption.text())
        self.assertIn('最小3×3セル',panel.timing_caption.text())
        self.assertIn('半径X=1 / Y=1',panel.timing_caption.text())
        timing=build_timeline(item)
        self.assertIn('start_unobserved',timing['quality_flags'])
        self.assertEqual(timing['candidates'],[])
        self.assertFalse(item.observed_open)

    def test_touch_trial_comparison_lists_walk_offsets_without_expanding_radius(self):
        from reconstruction.dialogue import Conversation
        from reconstruction.touch import context
        from tests.support.branches import NPC
        base=dict(NPC)
        first_npc=dict(base)
        first_npc['touch']=context(first_npc,dict(map_name=base['map_name'],x=base['x']-2,y=base['y'],
            position_basis='observed_walk_destination',packet_index=3,walk_send_packet_index=2),4)
        second_npc=dict(base)
        second_npc['touch']=context(second_npc,dict(map_name=base['map_name'],x=base['x'],y=base['y']+2,
            position_basis='observed_walk_destination',packet_index=8,walk_send_packet_index=7),9)
        first=Conversation(1,0,'flow',42,1,False,status='map_changed',npc=first_npc,
            termination=dict(timestamp=2,packet_index=4,packet_id=0x91,direction='RECV',connection='flow',source='TEST',
                fields=dict(map_name='target.gat',x=100,y=120,source_map_name=base['map_name'])))
        second=Conversation(2,0,'flow',42,3,False,status='map_changed',npc=second_npc,
            termination=dict(timestamp=4,packet_index=9,packet_id=0x91,direction='RECV',connection='flow',source='TEST',
                fields=dict(map_name='target.gat',x=100,y=120,source_map_name=base['map_name'])))
        w=self.window
        w.dialogues.sessions=[first,second]
        w.dialogues.touch_warp_inferences.append(dict(
            capture_session=0,flow_id='flow',packet_index=4,candidate_count=1,nearest_count=1,
            reason='unique_nearest_in_highest_priority_class',selected_actor_id=42))
        w.dialogues.touch_warp_inferences.append(dict(
            capture_session=0,flow_id='flow',packet_index=9,candidate_count=1,nearest_count=1,
            reason='unique_nearest_in_highest_priority_class',selected_actor_id=42))
        w.dialogues.revision+=1
        w.refresh_entity_views()
        panel=w.dialogue_panel
        caption=panel.timing_caption.text()
        self.assertIn('接触試行の比較',caption)
        self.assertIn('dx=-2 dy=0',caption)
        self.assertIn('dx=0 dy=2',caption)
        self.assertIn('暫定半径1は既定の仮値',caption)
        self.assertIn('歩行SEND#2',caption)
        evidence=json.loads(panel.evidence.toPlainText())
        self.assertEqual(len(evidence['touch_trial_comparison']),2)
        panel.merge_checkbox.setChecked(True)
        self.assertIn('接触試行の比較',panel.timing_caption.text())
        self.assertEqual(len(json.loads(panel.evidence.toPlainText())['touch_trial_comparison']),2)

    def test_unanswered_next_close_shows_timeout_suspicion_and_never_resumes_as_close2(self):
        from tests.support.dialogue import packet
        w = self.window
        for item in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                     packet(0xb4, struct.pack('<I', 42) + b'hello\0'), packet(0xb5, struct.pack('<I', 42)),
                     packet(0xb6, struct.pack('<I', 42)), packet(0x146, struct.pack('<I', 42), 'SEND'),
                     packet(0x1b3, b'portrait.bmp'.ljust(64, b'\0') + b'\x02')):
            w.add_packet(item)
        w.refresh_entity_views()
        panel = w.dialogue_panel
        self.assertIn('タイムアウト疑い', panel.code.toPlainText())
        self.assertNotIn('close2;', panel.code.toPlainText())
        labels = [panel.timeline.item(i, 6).text() for i in range(panel.timeline.rowCount())]
        self.assertIn('未応答終了・タイムアウト疑い', labels)
        self.assertTrue(w.dialogues.snapshot()['conversations'][0]['steps'][3]['timeout_suspected'])
        self.assertEqual(panel.timeline.item(3,3).text(),'未応答のまま終了')
        self.assertIn('未応答のままサーバー終了',panel.timing_caption.text())
        self.assertNotIn('入力要求の重複',panel.timing_caption.text())
        timeline=w.dialogues.snapshot()['timelines'][0]
        aborted=next(wait for wait in timeline['waits'] if wait.get('termination_reason'))
        self.assertEqual(aborted['prompt_kind'],'next')
        self.assertFalse(aborted['complete'])
        self.assertEqual(aborted['termination_packet_index'],3)


    def test_quest_commands_and_timeline_state_reference_keep_raw_state_without_checkquest_condition(self):
        from tests.unit.test_quest_observations import addition
        from tests.support.dialogue import packet
        w = self.window
        for item in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'), addition(),
                     packet(0x2b7, struct.pack('<IB', 12345, 2)), packet(0x2b4, struct.pack('<I', 12345)),
                     packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(item)
        w.refresh_entity_views()
        panel = w.dialogue_panel
        self.assertIn('setquest 12345;', panel.code.toPlainText())
        self.assertIn('delquest 12345;', panel.code.toPlainText())
        self.assertNotIn('checkquest(', panel.code.toPlainText())
        values = [panel.timeline.item(i, 7).text() for i in range(panel.timeline.rowCount())]
        from reconstruction.client_names import quest_reference
        prefix=quest_reference(w.client_names,12345)
        self.assertIn(prefix+' / state=1（受信値）', values)
        self.assertIn(prefix+' / state=2（受信値）', values)
        self.assertIn(prefix+' / 削除通知', values)
        index = values.index(prefix+' / state=2（受信値）')
        panel.timeline.selectRow(index)
        panel.jump()
        self.assertEqual(w.table.currentRow(), 2)
        # Quest tab lists chronological setquest/delquest; neither row is showevent-linked here.
        self.assertEqual(panel.quest_flow.rowCount(), 2)
        self.assertEqual([panel.quest_flow.item(i, 1).text() for i in range(2)], ['setquest', 'delquest'])
        self.assertEqual([panel.quest_flow.item(i, 3).text() for i in range(2)], ['未関連', '未関連'])

    def test_quest_showevent_emits_onquestinfo_and_marks_quest_tab_linked(self):
        from reconstruction.quests import ADD_LENGTHS
        from tests.support.dialogue import packet
        w = self.window
        name = 'レイジー#ep20_end01'
        addition = packet(
            0xb0c, struct.pack('<IBIIH', 3593, 1, 0, 999, 2) + bytes(ADD_LENGTHS[0xb0c] - 17),
            connection='flow-a', flow='')
        for item in (
                map_packet(), actor_packet(name=name),
                packet(0x90, struct.pack('<IB', 42, 1), 'SEND', connection='flow-a', flow=''),
                packet(0xb4, struct.pack('<I', 42) + b'hello\0', connection='flow-a', flow=''),
                addition,
                packet(0x446, struct.pack('<IHHHH', 42, 368, 222, 0, 1), connection='flow-a', flow=''),
                packet(0xb6, struct.pack('<I', 42), connection='flow-a', flow='')):
            w.add_packet(item)
        w.refresh_entity_views()
        panel = w.dialogue_panel
        code = panel.code.toPlainText()
        self.assertIn('OnQuestInfo:', code)
        self.assertIn('showevent 0, 1, "レイジー#ep20_end01";', code)
        self.assertIn('// 3593: 368, 222', code)
        self.assertIn('クエスト', [panel.details_tabs.tabText(i) for i in range(panel.details_tabs.count())])
        self.assertEqual(panel.quest_flow.rowCount(), 1)
        self.assertEqual(panel.quest_flow.item(0, 1).text(), 'setquest')
        self.assertEqual(panel.quest_flow.item(0, 3).text(), '0, 1')
        self.assertEqual(panel.quest_flow.item(0, 4).text(), name)
        self.assertEqual(panel.quest_flow.item(0, 5).text(), '368, 222')
        panel.quest_flow.selectRow(0)
        panel.jump_quest_link()
        self.assertGreaterEqual(w.table.currentRow(), 0)

    def test_quest_counter_has_external_display_and_related_timeline_without_generated_condition(self):
        from tests.unit.test_quest_observations import counter
        from tests.support.dialogue import packet
        w = self.window
        for item in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'), counter(),
                     packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(item)
        w.refresh_entity_views()
        self.assertIn('クエスト目標更新 layout=0AFE', w.display_log.toPlainText())
        self.assertIn('65535', w.display_log.toPlainText())
        self.assertEqual(w.dialogues.sessions[0].resource_observations[0]['fields']['objective_kind'], 'indexed_objective_id')
        self.assertIn('クエスト目標更新', w.dialogue_panel.code.toPlainText())
        labels = [w.dialogue_panel.timeline.item(i, 4).text() for i in range(w.dialogue_panel.timeline.rowCount())]
        self.assertIn('クエスト目標数観測', labels)
        self.assertNotIn('\nif ', w.dialogue_panel.code.toPlainText())

    def test_quest_notifications_appear_in_global_and_dialogue_evidence_as_observation_comments(self):
        from tests.unit.test_quest_observations import addition
        from tests.support.dialogue import packet
        w = self.window
        for item in (addition(), packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                     packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                     packet(0x2b4, struct.pack('<I', 12345)), packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(item)
        w.refresh_entity_views()
        observations = json.loads(w.dialogue_panel.presentations.toPlainText())
        self.assertEqual(len(observations['quest_observations']), 2)
        self.assertEqual(observations['quest_observations'][0]['context'], 'outside_dialogue')
        self.assertEqual(w.dialogues.sessions[0].resource_observations[0]['kind'], 'quest_delete')
        self.assertIn('クエスト削除 ID=12345', w.dialogue_panel.code.toPlainText())
        labels = [w.dialogue_panel.timeline.item(row, 4).text() for row in range(w.dialogue_panel.timeline.rowCount())]
        self.assertIn('クエスト削除観測', labels)

    def test_valued_effect_is_visible_in_dialogue_evidence_without_executable_downgrade(self):
        from tests.support.world import packet
        w = self.window
        for item in (map_packet(), actor_packet(),
                     packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'),
                     packet(0x284, struct.pack('<III', 42, 333, 12345)),
                     packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(item)
        w.refresh_entity_views()
        self.assertIn('@misceffect_value 333,12345;', w.display_log.toPlainText())
        code = w.dialogue_panel.code.toPlainText()
        self.assertIn('effect=333, value=12345', code)
        self.assertNotIn('\nmisceffect ', code)
        self.assertEqual(w.dialogues.sessions[0].steps[1]['fields'], {'effect_id': 333, 'value': 12345})
        self.assertEqual(w.dialogue_panel.timeline.item(1, 4).text(), '値付きエフェクト')

    def test_shop_observation_and_confirmation_keep_initial_hidden_after_current_state_changes(self):
        from tests.unit.test_npc_initial_state import actor
        from tests.unit.test_actor_identity import connection
        from tests.support.world import packet
        from tests.support.display import variable
        from dataclasses import replace
        from gui.shops import ShopExportDialog
        w = self.window
        endpoint = connection()
        for item in (map_packet(connection=endpoint), actor(2),
                     packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 0, 0), connection=endpoint),
                     packet(0x90, struct.pack('<IB', 42, 1), connection=endpoint, direction='SEND'),
                     packet(0xc4, struct.pack('<I', 42), connection=endpoint),
                     packet(0xc5, struct.pack('<IB', 42, 0), connection=endpoint, direction='SEND'),
                     replace(variable(0xc6, struct.pack('<IIBI', 100, 76, 3, 501), endpoint), timestamp=1)):
            w.add_packet(item)
        record = w.shops.records[0]
        self.assertEqual(record['npc']['initial_options'], 2)
        self.assertEqual(record['npc']['initial_state_evidence']['packet_index'], 1)
        dialog = ShopExportDialog(record, w.dialogues.sessions[0], w.shop_panel)
        self.assertIn('初回状態=hidden', dialog.npc_info.text())
        dialog.confirm_ids.setChecked(True)
        dialog.generate()
        self.assertIsNotNone(dialog.result_text)
        self.assertTrue(all(not line or line.startswith('//') for line in dialog.result_text.splitlines()))
        self.assertEqual(w.world.records('NPC')[0].options, 0)
        dialog.close()

    def test_npc_initial_hidden_state_remains_in_details_dialogue_and_bulk_export_after_state_change(self):
        from tests.unit.test_npc_initial_state import actor
        from tests.unit.test_actor_identity import connection
        from tests.support.world import packet
        from tests.support.display import variable
        from dataclasses import replace
        w = self.window
        endpoint = connection()
        for item in (map_packet(connection=endpoint), actor(2),
                     packet(0x229, struct.pack('<IHHIB', 42, 0, 0, 0, 0), connection=endpoint),
                     packet(0x90, struct.pack('<IB', 42, 1), connection=endpoint, direction='SEND'),
                     replace(variable(0xb4, struct.pack('<I', 42) + b'hello\0', endpoint), timestamp=1),
                     packet(0xb6, struct.pack('<I', 42), connection=endpoint)):
            w.add_packet(item)
        w.refresh_entity_views()
        w.npc_panel.table.setCurrentIndex(w.npc_panel.model.index(0, 0))
        self.assertIn('初回観測オプション: 0x00000002', w.npc_panel.detail.toPlainText())
        self.assertEqual(w.world.records('NPC')[0].options, 0)
        self.assertEqual(w.dialogues.sessions[0].npc['initial_options'], 2)
        destination = Path(self.log_folder.name) / 'initial-state-npcs.json'
        with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            w.save_all_npcs()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertIn('\tscript(HIDDEN)\t', saved['auriga'])
        self.assertEqual(saved['entries'][0]['entities'][0]['initial_options'], 2)
        self.assertEqual(saved['entries'][0]['entities'][0]['initial_state_evidence']['packet_index'], 1)

    def test_actor_history_groups_server_id_across_visibility_and_client_ports_and_navigates_evidence(self):
        from copy import deepcopy
        from reconstruction.world import WorldStore
        from tests.support.world import packet
        from tests.unit.test_actor_identity import connection
        for kind, actor_type, panel in (('NPC', 6, self.window.npc_panel), ('MOB', 5, self.window.mob_panel)):
            world = WorldStore()
            endpoint = connection()
            for item in (actor_packet(actor_id=1001, actor_type=actor_type, connection=endpoint),
                         packet(0x80, struct.pack('<IB', 1001, 0), connection=endpoint),
                         actor_packet(actor_id=1001, actor_type=actor_type, connection=endpoint),
                         actor_packet(actor_id=1001, actor_type=actor_type, connection=connection(client_port=50001)),
                         actor_packet(actor_id=1001, actor_type=actor_type, connection=connection(port=5122))):
                world.apply(item)
            before = deepcopy(world.snapshot())
            panel.set_records(world.records(kind))
            selected = next(i for i, row in enumerate(panel.model.rows) if row.connection == endpoint and row.appearance == 2)
            panel.table.setCurrentIndex(panel.model.index(selected, 0))
            history = panel.actor_history
            self.assertEqual(history.table.rowCount(), 3)
            self.assertIn('18.1.2.3:5121', history.caption.text())
            history.table.selectRow(0)
            with patch.object(history, 'on_source') as navigate:
                history.first_button.click()
                history.last_button.click()
            self.assertEqual([call.args[0] for call in navigate.call_args_list], [0, 1])
            panel.active_only.setChecked(True)
            self.assertEqual(history.table.rowCount(), 3)
            self.assertFalse(history.first_button.isEnabled())
            other = next(i for i, row in enumerate(panel.model.rows) if row.server_endpoint['port'] == 5122)
            panel.table.setCurrentIndex(panel.model.index(other, 0))
            self.assertEqual(history.table.rowCount(), 1)
            self.assertEqual(history.detail.toPlainText(), '')
            self.assertEqual(world.snapshot(), before)

    def test_actor_history_separates_captures_and_unknown_server_records_and_clears_empty_context(self):
        from reconstruction.world import WorldStore
        from tests.unit.test_actor_identity import connection
        world = WorldStore()
        for capture in (0, 1):
            world.apply(actor_packet(actor_id=1001, connection=connection()), session=capture)
        world.apply(actor_packet(actor_id=1001, connection='unresolved-a'), session=1)
        world.apply(actor_packet(actor_id=1001, connection='unresolved-b'), session=1)
        panel = self.window.npc_panel
        panel.set_records(world.records('NPC'))
        for index, item in enumerate(panel.model.rows):
            panel.table.setCurrentIndex(panel.model.index(index, 0))
            self.assertEqual(panel.actor_history.table.rowCount(), 1)
            self.assertEqual(panel.actor_history.rows[0]['capture_session'], item.capture_session)
        panel.actor_history.table.selectRow(0)
        self.assertTrue(panel.actor_history.first_button.isEnabled())
        panel.set_records([])
        self.assertEqual(panel.actor_history.rows, [])
        self.assertEqual(panel.actor_history.detail.toPlainText(), '')
        self.assertFalse(panel.actor_history.first_button.isEnabled())
        self.assertFalse(panel.actor_history.last_button.isEnabled())

    def test_external_review_navigation_merge_toggle_and_empty_selection_preserve_observations(self):
        from copy import deepcopy
        from tests.support.world import packet
        from tests.support.display import variable
        from dataclasses import replace
        w = self.window
        for item in (map_packet(), actor_packet(name='Speaker'), actor_packet(actor_id=43, name='Target'),
                     packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'),
                     replace(variable(0xb4, struct.pack('<I', 42) + b'hello\0', 'flow-a'), timestamp=1),
                     packet(0xc0, struct.pack('<IB', 43, 7)), packet(0xb6, struct.pack('<I', 42)),
                     packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'),
                     replace(variable(0xb4, struct.pack('<I', 42) + b'hello\0', 'flow-a'), timestamp=1),
                     packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(item)
        w.refresh_entity_views()
        panel = w.dialogue_panel
        panel.selection.setCurrentIndex(0)
        review = panel.external_presentations
        before = deepcopy(w.dialogues.snapshot())
        self.assertEqual(review.table.rowCount(), 1)
        review.table.selectRow(0)
        review.event_button.click()
        self.assertEqual(w.table.currentRow(), 5)
        review.anchor_button.click()
        self.assertEqual(w.table.currentRow(), 4)
        self.assertEqual(json.loads(review.detail.toPlainText())['actor_id'], 43)
        panel.selection.setCurrentIndex(1)
        self.assertEqual(review.table.rowCount(), 0)
        self.assertEqual(review.detail.toPlainText(), '')
        self.assertFalse(review.event_button.isEnabled())
        self.assertFalse(review.anchor_button.isEnabled())
        panel.merge_checkbox.setChecked(True)
        self.assertEqual(review.table.rowCount(), 1)
        self.assertIn('演出不一致 1経路', review.caption.text())
        self.assertFalse(review.event_button.isEnabled())
        review.table.selectRow(0)
        review.event_button.click()
        self.assertEqual(w.table.currentRow(), 5)
        self.assertEqual(w.dialogues.snapshot(), before)

    def test_external_unit_talk_stays_in_evidence_and_named_command_without_switching_npc(self):
        from tests.support.world import packet
        from tests.support.display import variable
        from dataclasses import replace
        w = self.window
        for item in (map_packet('1@toy.gat'), actor_packet(name='Speaker'), actor_packet(actor_id=43, name='Target'),
                     packet(0x90, struct.pack('<IB', 42, 1), direction='SEND'),
                     replace(variable(0xb4, struct.pack('<I', 42) + b'hello\0', 'flow-a'), timestamp=1),
                     replace(variable(0x8d, struct.pack('<I', 43) + b'outside words\0', 'flow-a'), timestamp=1),
                     packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(item)
        w.refresh_entity_views()
        self.assertEqual(len(w.dialogues.sessions), 1)
        self.assertEqual(w.dialogues.sessions[0].actor_id, 42)
        rows = json.loads(w.dialogue_panel.presentations.toPlainText())['observations']
        self.assertEqual(rows[0]['context'], 'external_candidate')
        self.assertEqual(rows[0]['actor_id'], 43)
        self.assertEqual(rows[0]['conversation_actor_id'], 42)
        self.assertFalse(rows[0]['cause_confirmed'])
        self.assertFalse(rows[0].get('adoption_confirmed'))
        code = w.dialogue_panel.code.toPlainText()
        self.assertIn('// unittalk getnpcid(0,getmdnpcname("Target")),"outside words";', code)
        self.assertTrue(all(not line.strip().startswith('unittalk getnpcid(0,') for line in code.splitlines()))
        w.dialogues.set_external_adoption(w.dialogues.sessions[0], rows[0]['packet_index'], True)
        w.refresh_entity_views()
        adopted = w.dialogue_panel.code.toPlainText()
        self.assertTrue(any(line.strip().startswith('unittalk getnpcid(0,') for line in adopted.splitlines()))

    def test_announcement_is_displayed_retained_and_included_in_active_dialogue(self):
        from tests.support.display import variable
        from tests.support.dialogue import packet
        from dataclasses import replace
        w = self.window
        w.add_packet(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        announcement = variable(0x1c3, struct.pack('<IHHHH', 0x123456, 400, 12, 0, 0) + b'notice\0')
        w.add_packet(replace(announcement, connection='half', flow_id='flow'))
        w.add_packet(packet(0xb6, struct.pack('<I', 42)))
        w.refresh_entity_views()
        self.assertIn('announce "notice", 0x9, 0x123456;', w.display_log.toPlainText())
        observations = json.loads(w.dialogue_panel.presentations.toPlainText())['observations']
        self.assertEqual(observations[0]['kind'], 'announcement')
        self.assertEqual(observations[0]['packet_index'], 2)
        self.assertFalse(observations[0]['target_observed'])
        self.assertEqual(observations[0]['npc'], {})
        self.assertIn('announce "notice",0x9,', w.dialogue_panel.code.toPlainText())

    def test_configured_editors_reject_unrelated_configuration_destinations(self):
        from tests.support.skills import mob, damage
        from tests.support.event_trials import repeated_report
        from reconstruction.mob_skill_export import build_candidates as skill_candidates
        from reconstruction.mob_spawn_export import build_candidates as spawn_candidates
        from gui.mob_skill_editor import MobSkillEditor
        from gui.mob_spawn_editor import MobSpawnEditor
        from gui.event_timer_editor import EventTimerEditor
        w = self.window
        for item in (map_packet(), mob(), damage()):
            w.add_packet(item)
        editors = [(MobSkillEditor(skill_candidates(w.skills.snapshot())['candidates'][0], {}, w),
                    'gui.mob_skill_editor', {'db_fields': {}}),
                   (MobSpawnEditor(spawn_candidates(w.mob_spawns.snapshot())['candidates'][0], {}, w),
                    'gui.mob_spawn_editor', {'placement_fields': {}}),
                   (EventTimerEditor(repeated_report('effect'), 0, w),
                    'gui.event_timer_editor', {'auriga': 'end;'})]
        target = Path(__file__).resolve().parents[2] / 'config' / 'ignorepacket.json'
        before = target.read_bytes()
        for editor, module, document in editors:
            with patch.object(editor, 'document', return_value=document), \
                    patch(module + '.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                    patch(module + '.QMessageBox.warning') as warning, \
                    patch(module + '.os.replace') as replace:
                editor.save()
                warning.assert_called_once()
                replace.assert_not_called()
            self.assertEqual(target.read_bytes(), before)
            editor.close()

    def test_player_and_combat_exports_freeze_data_sources_and_protect_inputs(self):
        from copy import deepcopy
        from tests.support.skills import mob
        from tests.support.combat import attack
        w = self.window
        for item in (map_packet(), mob(), attack()):
            w.add_packet(item)
        for panel, module in ((w.player_panel, 'gui.player'), (w.mob_performance_panel, 'gui.combat')):
            w.world_sources.clear()
            w.world_sources[0] = 'original-source.jsonl'
            expected = dict(deepcopy(panel.store.snapshot()), source_sessions={'0': 'original-source.jsonl'})
            destination = Path(self.log_folder.name) / f'{module}-frozen.json'
            def choose(*args):
                w.add_packet(map_packet(name='changed.gat'))
                w.add_packet(attack(tick=6000, timestamp=6))
                w.world_sources[999] = 'later-source.jsonl'
                return str(destination), ''
            with patch(module + '.QFileDialog.getSaveFileName', side_effect=choose):
                panel.save()
                self.wait_display_export()
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8')), json.loads(json.dumps(expected)))
            for protection in ('source', 'definitions', 'config', 'replacement'):
                w.world_sources.clear()
                w.path.setText('')
                target = destination
                if protection == 'source':
                    w.world_sources[0] = str(destination)
                elif protection == 'definitions':
                    w.path.setText(str(destination))
                elif protection == 'config':
                    target = Path(__file__).resolve().parents[2] / 'config' / 'auriga' / 'display.json'
                before = target.read_bytes()
                with patch(module + '.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                        patch(module + '.QMessageBox.critical') as warning, \
                        patch('storage.observation_export.os.replace', side_effect=OSError('replace failed')) as replace:
                    panel.save()
                    self.wait_display_export()
                    warning.assert_called_once()
                    self.assertEqual(replace.call_count, int(protection == 'replacement'))
                self.assertEqual(target.read_bytes(), before)

    def test_mob_spawn_and_skill_exports_freeze_reports_before_destination_dialog(self):
        from tests.support.skills import mob, damage
        from copy import deepcopy
        from reconstruction import mob_spawn_export, mob_skill_export
        w = self.window
        for item in (map_packet(), mob(), damage()):
            w.add_packet(item)
        for panel, module, exporter in ((w.mob_spawn_panel, 'gui.mob_spawns', mob_spawn_export),
                                         (w.mob_skills_panel, 'gui.skills', mob_skill_export)):
            for candidates, extension in ((False, 'json'), (True, 'json'), (True, 'txt')):
                sources = panel.sources if hasattr(panel, 'sources') else panel.source_sessions
                sources.pop(999, None)
                snapshot = deepcopy(panel.store.snapshot())
                if candidates:
                    expected = (exporter.build_candidates(snapshot, sources) if hasattr(panel, 'sources') else
                                exporter.build_candidates(snapshot, panel.names, sources))
                else:
                    expected = dict(snapshot, source_sessions=dict(sources))
                    if hasattr(panel, 'names'):
                        expected['source_sessions'] = {str(k): v for k, v in sources.items()}
                        expected['skill_names'] = {str(k): v for k, v in panel.names.items()}
                destination = Path(self.log_folder.name) / f'{module}-{candidates}.{extension}'
                def choose(*args):
                    sources[999] = 'later.jsonl'
                    w.add_packet(mob(77, class_id=1234))
                    w.add_packet(damage(77, skill=222))
                    return str(destination), ''
                with patch(module + '.QFileDialog.getSaveFileName', side_effect=choose):
                    (panel.save_candidates if candidates else panel.save)()
                    self.wait_display_export()
                text = destination.read_text(encoding='utf-8')
                if extension == 'json':
                    self.assertEqual(json.loads(text), json.loads(json.dumps(expected)))
                else:
                    self.assertEqual(text, exporter.render_candidates(expected))

    def test_mob_spawn_and_skill_exports_protect_inputs_and_failed_replacement(self):
        from tests.support.skills import mob, damage
        w = self.window
        for item in (map_packet(), mob(), damage()):
            w.add_packet(item)
        destination = Path(self.log_folder.name) / 'mob-preserved.json'
        destination.write_text('previous', encoding='utf-8')
        for panel, module in ((w.mob_spawn_panel, 'gui.mob_spawns'), (w.mob_skills_panel, 'gui.skills')):
            sources = panel.sources if hasattr(panel, 'sources') else panel.source_sessions
            for action in (panel.save, panel.save_candidates):
                for protection in ('source', 'definitions', 'config', 'replacement'):
                    sources.clear()
                    w.path.setText('')
                    target = destination
                    if protection == 'source':
                        sources[0] = str(destination)
                    elif protection == 'definitions':
                        w.path.setText(str(destination))
                    elif protection == 'config':
                        target = Path(__file__).resolve().parents[2] / 'config' / 'auriga' / 'dialogue.json'
                    before = target.read_bytes()
                    with patch(module + '.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                            patch(module + '.QMessageBox.warning') as warning, \
                            patch(module + '.QMessageBox.critical') as critical, \
                            patch('storage.observation_export.os.replace', side_effect=OSError('replace failed')) as replace:
                        action()
                        self.wait_display_export()
                        self.assertEqual(warning.call_count + critical.call_count, 1)
                        self.assertEqual(replace.call_count, int(protection == 'replacement'))
                    self.assertEqual(target.read_bytes(), before)

    def test_shop_exports_freeze_observations_and_confirmed_candidate_during_dialogs(self):
        from tests.unit.test_shop_export import observe_shop
        w, panel = self.window, self.window.shop_panel
        record, conversation = observe_shop(True)
        w.shops.records = [record]
        w.dialogues.sessions = [conversation]
        w.shops.revision += 1
        panel.refresh()
        destination = Path(self.log_folder.name) / 'frozen-shop.json'
        def choose_json(*args):
            record['items'][0]['price'] = 200
            panel.sources[999] = 'later.jsonl'
            return str(destination), ''
        with patch('gui.shops.QFileDialog.getSaveFileName', side_effect=choose_json):
            panel.save()
            self.wait_display_export()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(saved['records'][0]['items'][0]['price'], 100)
        self.assertNotIn('999', saved['source_sessions'])
        def generate(dialog):
            record['items'][0]['price'] = 300
            conversation.npc['name'] = 'changed'
            dialog.confirm_ids.setChecked(True)
            dialog.generate()
            return dialog.result()
        destination = Path(self.log_folder.name) / 'frozen-shop.txt'
        with patch('gui.shops.ShopExportDialog.exec', new=generate), \
                patch('gui.shops.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.export_candidate()
        text = destination.read_text(encoding='utf-8')
        self.assertIn('501:200', text)
        self.assertIn('callshop', text)
        self.assertNotIn('501:300', text)
        self.assertNotIn('changed', text)

    def test_shop_exports_protect_inputs_and_preserve_previous_file_on_replace_failure(self):
        from tests.unit.test_shop_export import observe_shop
        w, panel = self.window, self.window.shop_panel
        record, conversation = observe_shop(False)
        w.shops.records = [record]
        w.dialogues.sessions = [conversation]
        w.shops.revision += 1
        panel.refresh()
        destination = Path(self.log_folder.name) / 'shop-protected.txt'
        destination.write_text('previous', encoding='utf-8')
        def generate(dialog):
            dialog.confirm_ids.setChecked(True)
            dialog.generate()
            return dialog.result()
        for action in (panel.save, panel.export_candidate):
            for protection in ('source', 'definitions', 'config', 'replacement'):
                panel.sources.clear()
                w.path.setText('')
                target = destination
                if protection == 'source':
                    panel.sources[0] = str(destination)
                elif protection == 'definitions':
                    w.path.setText(str(destination))
                elif protection == 'config':
                    target = Path(__file__).resolve().parents[2] / 'config' / 'auriga' / 'shops.json'
                before = target.read_bytes()
                with patch('gui.shops.ShopExportDialog.exec', new=generate), \
                        patch('gui.shops.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                        patch('gui.shops.QMessageBox.warning') as warning, \
                        patch('storage.observation_export.os.replace', side_effect=OSError('replace failed')) as replace:
                    action()
                    warning.assert_called_once()
                    self.assertEqual(replace.call_count, int(protection == 'replacement'))
                self.assertEqual(target.read_bytes(), before)

    def test_dialogue_exports_freeze_content_and_mode_before_destination_dialog(self):
        from tests.support.branches import conversation
        w, panel = self.window, self.window.dialogue_panel
        for mode in ('body', 'json', 'merged', 'placed'):
            w.dialogues.sessions = [conversation(), conversation(2, 'second path', identifier=2)]
            w.dialogues.revision += 1
            panel.merge_checkbox.setChecked(False)
            panel.refresh()
            destination = Path(self.log_folder.name) / f'frozen-{mode}.txt'
            def choose(*args):
                w.dialogues.sessions.clear()
                w.dialogues.source_refs[999] = 'new-source.jsonl'
                w.dialogues.revision += 1
                panel.merge_checkbox.setChecked(True)
                panel.refresh()
                return str(destination), ''
            w.dialogues.source_refs.pop(999, None)
            with patch('gui.dialogues.QFileDialog.getSaveFileName', side_effect=choose):
                if mode == 'merged':
                    panel.save_merged()
                elif mode == 'placed':
                    panel.save_npc_file()
                else:
                    panel.save(mode == 'json')
            text = destination.read_text(encoding='utf-8')
            self.assertIn('one result', text)
            self.assertNotIn('new-source.jsonl', text)
            if mode in ('body', 'placed'):
                self.assertNotIn('second path', text)
            else:
                self.assertIn('second path', text)

    def test_dialogue_exports_protect_sources_definitions_config_and_failed_replacement(self):
        from tests.support.branches import conversation
        w, panel = self.window, self.window.dialogue_panel
        w.dialogues.sessions = [conversation()]
        w.dialogues.revision += 1
        panel.refresh()
        destination = Path(self.log_folder.name) / 'dialogue-protected.txt'
        destination.write_text('original', encoding='utf-8')
        actions = (lambda: panel.save(False), lambda: panel.save(True), panel.save_merged, panel.save_npc_file)
        for action in actions:
            for protection in ('source', 'definitions', 'config', 'replacement'):
                target = destination
                w.dialogues.source_refs.clear()
                w.path.setText('')
                if protection == 'source':
                    w.dialogues.source_refs[0] = str(destination)
                elif protection == 'definitions':
                    w.path.setText(str(destination))
                elif protection == 'config':
                    target = Path(__file__).resolve().parents[2] / 'config' / 'auriga' / 'dialogue.json'
                before = target.read_bytes()
                with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                        patch('gui.dialogues.QMessageBox.critical') as critical, \
                        patch('gui.dialogues.QMessageBox.warning') as warning, \
                        patch('storage.observation_export.os.replace', side_effect=OSError('replacement failed')) as replace:
                    action()
                    self.assertEqual(critical.call_count + warning.call_count, 1)
                    self.assertEqual(replace.call_count, int(protection == 'replacement'))
                self.assertEqual(target.read_bytes(), before)

    def test_large_npc_generation_freezes_before_dialog_supports_both_formats_and_cancel(self):
        from copy import deepcopy
        from dataclasses import asdict
        from threading import Event
        from PySide6.QtCore import QThread
        from reconstruction.world import Entity
        from reconstruction.report_snapshot import NpcReportSnapshot
        from reconstruction.npc_bundle import build_npc_bundle
        w=self.window
        original=NpcReportSnapshot.build
        for suffix,merge,cancel in [('.json',True,False),('.txt',False,False),('.txt',True,True)]:
            w.world.entities.clear()
            for index in range(101):
                entity=Entity(0,'flow',0,1000+index,1,'NPC',6,'test.gat',0,0,
                    name='Guide'+str(index),class_id=139,x=index,y=10,direction=0)
                w.world.entities[entity.key]=entity
            w.world_sources.clear();w.world_sources[0]='original.jsonl'
            w.dialogue_panel.merge_checkbox.setChecked(merge)
            expected=build_npc_bundle(w.world.snapshot('NPC')['entities'],[],dict(w.world_sources),merge=merge)
            target=Path(self.log_folder.name)/('generated-npcs'+suffix)
            target.write_bytes(b'original')
            entered=Event();release=Event();threads=[]
            previous=w.capture_log.toPlainText().count('配置を保存')
            def build(prepared):
                threads.append(QThread.currentThread()==self.app.thread())
                entered.set()
                if not release.wait(30):raise RuntimeError('generation gate timeout')
                return original(prepared)
            def choose(*args):
                next(iter(w.world.entities.values())).name='Later'
                w.world_sources[999]='later.jsonl'
                w.dialogue_panel.merge_checkbox.setChecked(not merge)
                return str(target),''
            with self.subTest(suffix=suffix,merge=merge,cancel=cancel),patch.object(NpcReportSnapshot,'build',new=build), \
                    patch('gui.main_window.QFileDialog.getSaveFileName',side_effect=choose):
                try:
                    w.save_all_npcs()
                    self.assertTrue(entered.wait(10))
                    self.assertEqual(w.capture_log.toPlainText().count('配置を保存'),previous)
                    if cancel:w.cancel_display_export()
                finally:
                    release.set();self.wait_display_export()
            self.assertEqual(threads,[False])
            if cancel:self.assertEqual(target.read_bytes(),b'original')
            elif suffix=='.json':self.assertEqual(json.loads(target.read_text(encoding='utf-8')),json.loads(json.dumps(expected)))
            else:self.assertEqual(target.read_text(encoding='utf-8'),expected['auriga'])
            self.assertEqual(w.capture_log.toPlainText().count('配置を保存'),previous+int(not cancel))

    def test_large_mob_generation_uses_detached_state_and_cancels_before_writing(self):
        from copy import deepcopy
        from threading import Event
        from PySide6.QtCore import QThread
        from reconstruction.report_snapshot import MobReportSnapshot
        from tests.support.skills import mob,damage
        from tests.support.combat import attack
        w=self.window
        w.add_packet(mob())
        for index in range(1002):
            w.skills.apply(damage(timestamp=index+1,tick=1000+index),packet_index=index+1)
            w.combat.apply(attack(timestamp=index+1,tick=1000+index),packet_index=index+1)
        original_build=MobReportSnapshot.build
        for panel,module,cancel in [(w.mob_skills_panel,'gui.skills',False),
                                    (w.mob_performance_panel,'gui.combat',False),
                                    (w.mob_skills_panel,'gui.skills',True)]:
            w.world_sources.clear();w.world_sources[0]='original.jsonl'
            expected=dict(deepcopy(panel.store.snapshot()),source_sessions={'0':'original.jsonl'})
            if module=='gui.skills':expected['skill_names']={str(k):v for k,v in panel.names.items()}
            target=Path(self.log_folder.name)/(module+'-generated.json')
            target.write_bytes(b'original')
            entered=Event();release=Event();threads=[]
            def build(snapshot):
                threads.append(QThread.currentThread()==self.app.thread())
                entered.set()
                if not release.wait(30):raise RuntimeError('generation gate timeout')
                return original_build(snapshot)
            def choose(*args):
                panel.store.events[-1]['flags'].append('later_change')
                w.world_sources[999]='later.jsonl'
                return str(target),''
            with self.subTest(module=module,cancel=cancel),patch.object(MobReportSnapshot,'build',new=build), \
                    patch(module+'.QFileDialog.getSaveFileName',side_effect=choose):
                try:
                    panel.save()
                    self.assertTrue(entered.wait(10))
                    self.assertIsNotNone(w.display_export)
                    if cancel:w.cancel_display_export()
                finally:
                    release.set()
                    self.wait_display_export()
            self.assertEqual(threads,[False])
            if cancel:self.assertEqual(target.read_bytes(),b'original')
            else:self.assertEqual(json.loads(target.read_text(encoding='utf-8')),json.loads(json.dumps(expected)))

    def test_large_mob_json_exports_freeze_before_dialog_and_share_one_save_slot(self):
        from copy import deepcopy
        w=self.window
        actions=[(lambda:w.save_entities('MOB'),'gui.main_window',w.world),
                 (w.mob_skills_panel.save,'gui.skills',w.skills),
                 (w.mob_performance_panel.save,'gui.combat',w.combat)]
        for action,module,store in actions:
            report={'schema_version':1,'entities':[],
                    'observations':[{'index':index,'text':'観測😀'} for index in range(3000)]}
            expected=deepcopy(report['observations'])
            w.world_sources.clear();w.world_sources[0]='original.jsonl'
            target=Path(self.log_folder.name)/(module+'-large.json')
            def choose(*args):
                report['observations'].append({'late':True})
                w.world_sources[999]='later.jsonl'
                return str(target),''
            with self.subTest(module=module),patch.object(store,'snapshot',return_value=report), \
                    patch(module+'.QFileDialog.getSaveFileName',side_effect=choose) as dialog:
                action()
                self.assertIsNotNone(w.display_export)
                action()
                self.assertEqual(dialog.call_count,1)
                self.wait_display_export()
            saved=json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(saved['observations'],expected)
            self.assertEqual(saved['source_sessions'],{'0':'original.jsonl'})

    def test_large_npc_text_export_reports_only_atomic_success_and_cancel_keeps_target(self):
        from threading import Event
        from storage.observation_export import save_observation_chunks
        from reconstruction.npc_bundle import build_npc_bundle
        w=self.window
        for packet in (map_packet(),actor_packet()):w.add_packet(packet)
        report=build_npc_bundle(w.world.snapshot('NPC')['entities'],[],w.world_sources)
        report['auriga']+='\n// synthetic observation\n'*12000
        target=Path(self.log_folder.name)/'large-npcs.txt'
        for cancel in (False,True):
            target.write_bytes(b'original')
            entered=Event();release=Event()
            before=w.capture_log.toPlainText().count('配置を保存')
            def paused(*args,**kwargs):
                entered.set()
                if not release.wait(30):raise RuntimeError('worker gate timeout')
                return save_observation_chunks(*args,**kwargs)
            with self.subTest(cancel=cancel),patch('reconstruction.npc_bundle.build_npc_bundle',return_value=report), \
                    patch('gui.observation_save.save_observation_chunks',side_effect=paused), \
                    patch('gui.main_window.QFileDialog.getSaveFileName',return_value=(str(target),'')):
                try:
                    w.save_all_npcs()
                    self.assertTrue(entered.wait(10))
                    self.assertEqual(w.capture_log.toPlainText().count('配置を保存'),before)
                    if cancel:w.cancel_display_export()
                finally:
                    release.set()
                    self.wait_display_export()
            self.assertEqual(w.capture_log.toPlainText().count('配置を保存'),before+int(not cancel))
            self.assertEqual(target.read_bytes(),b'original' if cancel else report['auriga'].encode('utf-8'))

    def test_entity_exports_freeze_snapshot_protect_sources_and_preserve_existing_file_on_failure(self):
        from tests.support.skills import mob
        w = self.window
        for item in (map_packet(), actor_packet(), mob(43)):
            w.add_packet(item)
        for kind in ('NPC', 'MOB'):
            destination = Path(self.log_folder.name) / f'{kind}-safe.json'
            before = w.world.snapshot(kind)
            def choose(*args):
                w.world_sources[999] = 'later-source.jsonl'
                w.add_packet(actor_packet(actor_id=50) if kind == 'NPC' else mob(51))
                return str(destination), ''
            w.world_sources.pop(999, None)
            with patch('gui.main_window.QFileDialog.getSaveFileName', side_effect=choose):
                w.save_entities(kind)
            saved = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(saved['entities'], before['entities'])
            self.assertNotIn('999', saved['source_sessions'])
            original = destination.read_bytes()
            w.world_sources[999] = str(destination)
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(destination), '')), \
                    patch('gui.main_window.QMessageBox.critical') as warning:
                w.save_entities(kind)
                warning.assert_called_once()
            self.assertEqual(destination.read_bytes(), original)
            w.world_sources.pop(999)
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(destination), '')), \
                    patch('storage.observation_export.os.replace', side_effect=OSError('replacement failed')), \
                    patch('gui.main_window.QMessageBox.critical') as warning:
                w.save_entities(kind)
                warning.assert_called_once()
            self.assertEqual(destination.read_bytes(), original)

    def test_export_all_npcs_menu_follows_dialogue_merge_checkbox_and_ignores_list_filter(self):
        from tests.support.dialogue import packet
        from tests.support.world import packet as world_packet
        w = self.window
        for event in (map_packet(), actor_packet(), actor_packet(actor_id=43, name='Other'),
                      name_packet(name='案内人'), name_packet(actor_id=43, name='Other')):
            w.add_packet(event)
        for choice in (1, 2):
            for event in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND', flow='flow-a', connection='flow-a'),
                          packet(0xb7, struct.pack('<I', 42) + b'one:two:\0', flow='flow-a', connection='flow-a'),
                          packet(0xb8, struct.pack('<IB', 42, choice), 'SEND', flow='flow-a', connection='flow-a'),
                          packet(0xb4, struct.pack('<I', 42) + f'result {choice}\0'.encode(), flow='flow-a', connection='flow-a'),
                          packet(0xb6, struct.pack('<I', 42), flow='flow-a', connection='flow-a')):
                w.add_packet(event)
        w.add_packet(world_packet(0x80, struct.pack('<IB', 43, 0), timestamp=3))
        w.refresh_entity_views()
        w.npc_panel.active_only.setChecked(True)
        self.assertEqual(w.npc_panel.model.rowCount(), 1)
        for merged in (False, True):
            w.dialogue_panel.merge_checkbox.setChecked(merged)
            destination = Path(self.log_folder.name) / f'all-{merged}.json'
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
                w.export_all_npcs_action.trigger()
            report = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(report['dialogue_merged'], merged)
            self.assertEqual(len(report['entries']), 2)
            self.assertEqual(report['auriga'].count("switch ('@menu)"), 1 if merged else 2)
            self.assertEqual(report['auriga'].count('OnInit:'), 2)
            initial = next(row for row in report['entries'] if row['npc']['actor_id'] == 43)
            self.assertTrue(initial['auriga'].split('OnInit:')[0].rstrip().endswith('end;'))

    def test_npc_metadata_only_save_works_without_dialogue_and_preserves_source_and_state(self):
        from copy import deepcopy
        w = self.window
        self.assertFalse(w.npc_metadata_export.isEnabled())
        for event in (map_packet(), actor_packet(), name_packet(name='案内人', title='案内役', group_id=9)):
            w.add_packet(event)
        w.refresh_entity_views()
        w.npc_panel.table.setCurrentIndex(w.npc_panel.model.index(0, 0))
        self.assertTrue(w.npc_metadata_export.isEnabled())
        self.assertFalse(w.dialogues.sessions)
        before = deepcopy(w.world.snapshot())
        for extension in ('txt', 'json'):
            path = Path(self.log_folder.name) / ('npc-init.' + extension)
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                w.save_npc_metadata()
            if extension == 'json':
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertFalse(saved['dialogue_included'])
                self.assertEqual(saved['entity']['group_id'], 9)
                text = saved['auriga']
            else:
                text = path.read_text(encoding='utf-8')
            self.assertIn('OnInit:', text)
            self.assertIn('setnpctitle "案内役";', text)
            self.assertIn('会話本文・起因条件は含みません', text)
        source = Path(self.log_folder.name) / 'source.txt'
        source.write_bytes(b'original input')
        w.world_sources[0] = str(source)
        with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(source), '')), \
                patch('gui.main_window.QMessageBox.warning') as warning:
            w.save_npc_metadata()
        warning.assert_called_once()
        self.assertEqual(source.read_bytes(), b'original input')
        self.assertEqual(w.world.snapshot(), before)
        self.assertFalse(w.dialogues.sessions)

    def test_adf_metadata_generates_npc_init_and_mob_log_and_individual_details(self):
        from tests.support.dialogue import packet
        w = self.window
        for record in (map_packet(), actor_packet(), actor_packet(actor_id=43, actor_type=5),
                       name_packet(name='案内人', title='案内役', group_id=9),
                       name_packet(actor_id=43, name='MOB', title='BOSS', group_id=8),
                       packet(0x90, struct.pack('<IB', 42, 1), 'SEND', flow='flow-a', connection='flow-a'),
                       packet(0xb4, struct.pack('<I', 42) + b'hello\0', flow='flow-a', connection='flow-a'),
                       packet(0xb6, struct.pack('<I', 42), flow='flow-a', connection='flow-a')):
            w.add_packet(record)
        w.refresh_entity_views()
        w.dialogue_panel.refresh()
        text = w.dialogue_panel.code.toPlainText()
        self.assertEqual(text.count('OnInit:'), 1)
        self.assertIn('setnpcgroup 9;', text)
        self.assertIn('setnpctitle "案内役";', text)
        log = w.display_log.toPlainText()
        self.assertIn('setnpcgroup 9;\t// NPC 42 "案内人"', log)
        self.assertIn('setnpctitle "案内役";\t// NPC 42 "案内人"', log)
        self.assertNotIn('OnInit:', log)
        self.assertIn('setunitgroup 8,43;', log)
        self.assertIn('setunittitle "BOSS",43;', log)
        model = w.mob_panel.model
        row = next(i for i, entity in enumerate(model.rows) if entity.actor_id == 43)
        w.mob_panel.table.setCurrentIndex(model.index(row, 0))
        self.assertIn('グループ: 8', w.mob_panel.detail.toPlainText())
        self.assertIn('BOSS', w.mob_panel.detail.toPlainText())
        self.assertIn('setunittitle "BOSS",43;', w.mob_panel.detail.toPlainText())
        npc_row = next(i for i, entity in enumerate(w.npc_panel.model.rows) if entity.actor_id == 42)
        w.npc_panel.table.setCurrentIndex(w.npc_panel.model.index(npc_row, 0))
        detail = w.npc_panel.detail.toPlainText()
        self.assertIn('setnpcgroup 9;\t// NPC 42 "案内人"', detail)
        self.assertNotIn('OnInit:', detail)
        snapshot = w.world.snapshot()
        w.reload_display()
        self.assertEqual(w.world.snapshot(), snapshot)
        self.assertIn('setunitgroup 8,43;', w.display_log.toPlainText())
        self.assertIn('setnpcgroup 9;\t// NPC 42 "案内人"', w.display_log.toPlainText())

    def test_mob_observation_exports_reject_sources_and_keep_existing_reports_on_failure(self):
        w = self.window
        source = Path(self.log_folder.name) / 'capture.jsonl'
        source.write_bytes(b'original capture')
        w.world_sources[0] = str(source)
        for panel, module in ((w.mob_skills_panel, 'gui.skills'), (w.mob_performance_panel, 'gui.combat')):
            with self.subTest(module=module):
                with patch(module + '.QFileDialog.getSaveFileName', return_value=(str(source), '')), \
                        patch(module + '.QMessageBox.critical') as warning:
                    panel.save()
                    self.wait_display_export()
                warning.assert_called_once()
                self.assertEqual(source.read_bytes(), b'original capture')
                destination = Path(self.log_folder.name) / (module + '.json')
                destination.write_bytes(b'old report')
                with patch(module + '.QFileDialog.getSaveFileName', return_value=(str(destination), '')), \
                        patch('storage.observation_export.os.replace', side_effect=OSError('locked')), \
                        patch(module + '.QMessageBox.critical') as warning:
                    panel.save()
                    self.wait_display_export()
                warning.assert_called_once()
                self.assertEqual(destination.read_bytes(), b'old report')

    def test_attack_interval_navigation_separates_hp_sp_individual_and_target(self):
        from copy import deepcopy
        from tests.support.skills import mob
        from tests.support.combat import attack
        w = self.window
        events = [mob(42), mob(43), attack(actor=42), attack(actor=43, tick=1100, timestamp=1.1),
                  attack(actor=42, target=100, tick=1200, timestamp=1.2),
                  attack(actor=42, tick=6000, timestamp=6),
                  attack(actor=42, tick=7000, timestamp=7, sp=1),
                  attack(actor=42, tick=9000, timestamp=9, sp=1)]
        for event in events:
            w.add_packet(event)
        w.refresh_entity_views()
        panel = w.mob_performance_panel
        before = deepcopy(w.combat.snapshot())
        panel.table.selectRow(0)
        self.assertEqual(panel.interval_table.rowCount(), 2)
        self.assertEqual([panel.interval_table.item(i, 0).text() for i in range(2)], ['与HP', '与SP'])
        self.assertEqual([panel.interval_table.item(i, 5).text() for i in range(2)], ['5000', '2000'])
        self.assertEqual(panel.interval_table.item(0, 2).text(), '99')
        self.assertEqual(panel.interval_table.item(0, 3).text(), '未観測')
        destinations = []
        with patch.object(panel, 'on_source', side_effect=destinations.append):
            for row in range(2):
                panel.interval_table.setCurrentCell(row, 0)
                panel.interval_start.click()
                panel.interval_end.click()
            panel.scope.setCurrentIndex(1)
            panel.set_entity(None)
            self.assertEqual(panel.interval_table.rowCount(), 0)
            self.assertFalse(panel.interval_start.isEnabled())
            panel.jump_interval('packet_index')
        self.assertEqual(destinations, [2, 5, 6, 7])
        self.assertEqual(w.combat.snapshot(), before)

    def test_cast_candidate_paging_preserves_all_links_and_endpoints(self):
        from copy import deepcopy
        from tests.support.skills import mob,cast,damage
        w=self.window;w.add_packet(mob())
        for index in range(1003):
            stamp=index*2+1
            w.skills.apply(cast(timestamp=stamp),packet_index=index*2+1)
            w.skills.apply(damage(timestamp=stamp+.1,tick=(index+1)*1000,level=3),packet_index=index*2+2)
        before=deepcopy(w.skills.snapshot())
        panel=w.mob_skills_panel;panel.refresh();panel.table.selectRow(0)
        view=panel.cast_review
        self.assertEqual(len(view.pager.rows),1003)
        self.assertEqual(view.table.rowCount(),3)
        view.pager.previous.click()
        self.assertEqual(view.table.rowCount(),1000)
        view.table.selectRow(0)
        with patch.object(panel,'on_source') as source:
            view.start.click();view.end.click()
        self.assertEqual([c.args[0] for c in source.call_args_list],[1,2])
        panel.rebuild()
        self.assertEqual(view.pager.page,0)
        self.assertEqual(len(view.pager.rows),1003)
        self.assertEqual(w.skills.snapshot(),before)
        panel.scope.setCurrentIndex(1);panel.set_entity(None)
        self.assertEqual(view.table.rowCount(),0)
        self.assertFalse(view.pager.next.isEnabled())
        self.assertFalse(view.start.isEnabled());self.assertFalse(view.end.isEnabled());self.assertFalse(view.tracking.isEnabled())
        with patch.object(panel,'on_source') as source:view.jump('from_packet_index')
        source.assert_not_called()

    def test_cast_candidate_navigation_distinguishes_pending_followup_and_preserves_observations(self):
        from copy import deepcopy
        from tests.support.skills import mob, damage, cast
        w = self.window
        for event in (mob(), cast(timestamp=.5), damage(timestamp=1), cast(timestamp=2)):
            w.add_packet(event)
        w.refresh_entity_views()
        panel = w.mob_skills_panel
        panel.table.selectRow(0)
        view = panel.cast_review
        before = deepcopy(w.skills.snapshot())
        self.assertEqual(view.table.rowCount(), 2)
        self.assertIn('候補', view.table.item(0, 4).text())
        self.assertEqual(view.table.item(1, 4).text(), '後続未観測')
        destinations = []
        with patch.object(panel, 'on_source', side_effect=destinations.append):
            view.table.setCurrentCell(0, 0)
            view.start.click()
            view.end.click()
            view.table.setCurrentCell(1, 0)
            self.assertTrue(view.start.isEnabled())
            self.assertFalse(view.end.isEnabled())
            view.jump('packet_index')
            view.start.click()
        self.assertEqual(destinations, [1, 2, 3])
        self.assertEqual(w.skills.snapshot(), before)
        from tests.support.world import packet as world_packet
        w.add_packet(world_packet(0x80, struct.pack('<IB', 42, 0), timestamp=3))
        w.refresh_entity_views()
        panel.table.selectRow(0)
        view.table.setCurrentCell(1, 0)
        self.assertTrue(view.tracking.isEnabled())
        self.assertFalse(view.end.isEnabled())
        with patch.object(panel, 'on_source') as tracking_source:
            view.tracking.click()
        tracking_source.assert_called_once_with(4)

    def test_effect_interval_navigation_keeps_individual_endpoints_and_clears_stale_selection(self):
        from copy import deepcopy
        from tests.support.skills import mob, damage
        from tests.support.world import packet
        w = self.window
        w.add_packet(mob(42))
        w.add_packet(mob(43))
        for actor, timestamp in ((42, 1), (43, 1.5), (42, 3)):
            w.add_packet(packet(0x11a, struct.pack('<HhIIB', 347, 100, 99, actor, 1), timestamp=timestamp))
        w.add_packet(damage(timestamp=4))
        w.refresh_entity_views()
        panel = w.mob_skills_panel
        before = deepcopy(w.skills.snapshot())
        row = next(i for i, item in enumerate(panel.rows) if item['skill_id'] == 347)
        panel.table.selectRow(row)
        self.assertEqual(panel.interval_table.rowCount(), 1)
        self.assertIn('/42/', panel.interval_table.item(0, 1).text())
        self.assertEqual(panel.interval_table.item(0, 2).text(), '99')
        self.assertEqual(float(panel.interval_table.item(0, 4).text()), 2000)
        panel.interval_table.setCurrentCell(0, 0)
        self.assertTrue(panel.interval_start.isEnabled())
        destinations = []
        with patch.object(panel, 'on_source', side_effect=destinations.append):
            panel.interval_start.click()
            panel.interval_end.click()
            row = next(i for i, item in enumerate(panel.rows) if item['skill_id'] == 177)
            panel.table.selectRow(row)
            self.assertEqual(panel.interval_table.rowCount(), 0)
            self.assertFalse(panel.interval_start.isEnabled())
            self.assertFalse(panel.interval_end.isEnabled())
            panel.jump_interval('packet_index')
        self.assertEqual(destinations, [2, 4])
        self.assertEqual(w.skills.snapshot(), before)

    def test_excluded_review_selects_partial_conversation_and_source_without_completing_it(self):
        from copy import deepcopy
        from tests.support.dialogue import packet
        w = self.window
        from dataclasses import replace
        event=actor_packet(connection='game')
        raw=bytearray(event.raw);struct.pack_into('<H',raw,23,100)  # A non-contact class keeps the opening genuinely unobserved.
        w.add_packet(replace(event,raw=bytes(raw)))
        for record in (packet(0xb4, struct.pack('<I', 42) + b'partial\0', flow='game', connection='game'),
                       packet(0xb6, struct.pack('<I', 42), flow='game', connection='game'),
                       packet(0x90, struct.pack('<IB', 42, 1), 'SEND', flow='game', connection='game'),
                       packet(0xb4, struct.pack('<I', 42) + b'complete\0', flow='game', connection='game'),
                       packet(0xb6, struct.pack('<I', 42), flow='game', connection='game')):
            w.add_packet(record)
        before = deepcopy(w.dialogues.snapshot())
        panel = w.dialogue_panel
        panel.refresh()
        self.assertEqual(panel.review_table.rowCount(), 1)
        self.assertIn('開始操作未観測', panel.review_table.item(0, 3).text())
        panel.selection.setCurrentIndex(1)
        panel.review_table.setCurrentCell(0, 0)
        with patch.object(panel, 'show_source') as source:
            panel.open_review()
        source.assert_called_once_with(1)
        self.assertEqual(panel.selected().id, 1)
        self.assertFalse(panel.selected().observed_open)
        self.assertIn('mes "partial";', panel.code.toPlainText())
        self.assertEqual(w.dialogues.snapshot(), before)

    def test_player_login_map_populates_npc_mob_dialogue_and_spawn_candidates(self):
        from dataclasses import replace
        from tests.support.player import packet as player_packet, character_list
        from tests.support.dialogue import packet as dialogue_packet
        from reconstruction.mob_spawn_export import build_candidates
        w = self.window
        w.add_packet(player_packet(0x65, struct.pack('<I', 42) + bytes(11), flow='char', direction='SEND'))
        w.add_packet(character_list())
        w.player_panel.refresh()
        self.assertFalse(w.players.states)
        self.assertEqual(w.player_panel.characters.rowCount(), 1)
        w.add_packet(player_packet(0x71, struct.pack('<I', 123) + b'test.gat'.ljust(16, b'\0') + bytes(6), flow='char'))
        w.add_packet(player_packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND', flow='game'))
        for actor, kind in ((70, 6), (71, 5)):
            w.add_packet(replace(actor_packet(actor_id=actor, actor_type=kind, connection='game'), flow_id='game'))
        w.add_packet(dialogue_packet(0x90, struct.pack('<IB', 70, 1), 'SEND', flow='game', connection='send'))
        w.add_packet(dialogue_packet(0xb4, struct.pack('<I', 70) + b'hello\0', flow='game', connection='game'))
        w.refresh_entity_views()
        self.assertTrue(all(entity.map_name == 'test.gat' for entity in w.world.records()))
        self.assertEqual(w.dialogues.sessions[0].npc['map_name'], 'test.gat')
        self.assertEqual(w.dialogues.sessions[0].npc['map_origin'], 'player_current_map')
        self.assertEqual(w.mob_spawns.snapshot()['groups'][0]['map_name'], 'test.gat')
        candidate = build_candidates(w.mob_spawns.snapshot())['candidates'][0]
        self.assertEqual(candidate['placement_fields']['map_name'], 'test.gat')
        self.assertEqual(candidate['observed']['map_evidence']['map_hint']['packet_index'], 2)
        w.player_panel.refresh()
        self.assertIn('hero', w.player_panel.detail_label.text())
        self.assertIn(str(2**40), w.player_panel.detail_label.text())
        self.assertEqual(w.players.states[(0, 'game')].zeny, 1000)
        panel = w.player_panel
        panel.characters.setCurrentCell(0, 5)
        status_index = len(w.events)
        w.add_packet(player_packet(0xb1, struct.pack('<HI', 20, 1200)))
        panel.refresh()
        self.assertEqual(panel.characters.item(0, 5).text(), '1,200')
        panel.jump_character()
        self.assertEqual(w.table.currentRow(), status_index)
        selected_connection = panel.selection.currentData()
        w.add_packet(replace(character_list(name='unbound'), flow_id='unbound', connection='unbound'))
        panel.refresh()
        self.assertEqual(panel.characters.rowCount(), 2)
        self.assertEqual(panel.characters.item(1, 0).text(), '不明')
        self.assertEqual(panel.selection.currentData(), selected_connection)
        list_index = len(w.events)
        w.add_packet(character_list(zeny=1500))
        panel.refresh()
        self.assertEqual(panel.characters.currentRow(), 1)
        self.assertEqual(panel.characters.item(1, 0).text(), '42')
        self.assertEqual(panel.characters.item(1, 5).text(), '1,500')
        self.assertIn('character_list', panel.character_detail.toPlainText())
        panel.jump_character()
        self.assertEqual(w.table.currentRow(), list_index)
        destination = Path(self.log_folder.name) / 'player.json'
        with patch('gui.player.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
            self.wait_display_export()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(len(saved['characters']), 2)
        self.assertEqual(saved['states'][0]['zeny'], 1200)
        w.players.begin_capture(1)
        panel.refresh()
        self.assertEqual(panel.characters.rowCount(), 0)
        self.assertEqual(panel.character_detail.toPlainText(), '')

    def test_shop_observations_keep_target_prices_and_export_source(self):
        from dataclasses import replace
        w = self.window
        w.add_packet(map_packet())
        actor = actor_packet()
        w.add_packet(actor)
        # Shop selectors and lists share the observed NPC's transport flow.
        selector = replace(actor, packet_id=0xc4, raw=struct.pack('<HI', 0xc4, 42))
        w.add_packet(selector)
        w.add_packet(replace(selector, direction='SEND', packet_id=0xc5, raw=struct.pack('<HIB', 0xc5, 42, 0)))
        raw = struct.pack('<HHIIBI', 0xc6, 17, 100, 76, 3, 70000)
        listing = replace(selector, packet_id=0xc6, raw=raw)
        w.add_packet(listing)
        w.refresh_entity_views()
        panel = w.shop_panel
        self.assertEqual(panel.selection.count(), 1)
        self.assertEqual(panel.table.item(0, 0).text(), '70000')
        self.assertEqual(panel.table.item(0, 1).text(), '100')
        self.assertEqual(panel.table.item(0, 2).text(), '76')
        self.assertEqual(w.shops.records[0]['npc']['name'], '案内人')
        panel.jump()
        self.assertEqual(w.table.currentRow(), 4)
        before = w.shops.snapshot()
        w.reload_display()
        self.assertEqual(w.shops.snapshot(), before)
        destination = Path(self.log_folder.name) / 'shops.json'
        with patch('gui.shops.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
            self.wait_display_export()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(saved['records'][0]['items'][0]['client_item_id'], 70000)
        self.assertFalse(saved['records'][0]['cause_confirmed'])
        from gui.shops import ShopExportDialog
        dialog = ShopExportDialog(w.shops.records[0], None, panel)
        try:
            with patch('gui.shops.QMessageBox.warning') as warning:
                dialog.generate()
            warning.assert_called_once()
            self.assertIsNone(dialog.result_text)
        finally:
            dialog.close()
        def generate_dialog(dialog):
            dialog.confirm_ids.setChecked(True)
            dialog.generate()
            return dialog.result()
        candidate_path = Path(self.log_folder.name) / 'shop.txt'
        with patch('gui.shops.ShopExportDialog.exec', new=generate_dialog), \
             patch('gui.shops.QFileDialog.getSaveFileName', return_value=(str(candidate_path), '')):
            panel.export_candidate()
        self.assertIn('\tshop\t案内人\t45,70000:100', candidate_path.read_text(encoding='utf-8'))
        self.assertEqual(w.shops.snapshot(), before)

    def test_dialogue_preview_source_and_export_are_independent_of_display(self):
        from tests.support.dialogue import packet
        w = self.window
        w.add_packet(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        w.add_packet(packet(0xb1, struct.pack('<HI', 20, 1000)))
        w.add_packet(packet(0xc0, struct.pack('<IB', 42, 3)))
        w.add_packet(packet(0xb6, struct.pack('<I', 42)))
        w.refresh_entity_views()
        panel = w.dialogue_panel
        self.assertEqual(panel.selection.count(), 1)
        self.assertIn('mes "hello";', panel.code.toPlainText())
        self.assertIn('emotion 3;', panel.code.toPlainText())
        self.assertIn('Zeny 1000', panel.code.toPlainText())
        self.assertTrue(any(panel.timeline.item(row, 4).text() == 'Zeny観測'
                            for row in range(panel.timeline.rowCount())))
        with patch('gui.dialogues.QFileDialog.getSaveFileName') as chooser, \
             patch('gui.dialogues.QMessageBox.warning') as warning:
            panel.save_npc_file()
        chooser.assert_not_called()
        warning.assert_called_once()
        before = w.dialogues.snapshot()
        w.display_timestamps.setChecked(True)
        w.reload_display()
        self.assertEqual(w.dialogues.snapshot(), before)
        panel.jump()
        self.assertIs(w.workspace_tabs.currentWidget(), w.packet_page)
        self.assertEqual(w.table.currentRow(), 0)
        destination = Path(self.log_folder.name) / 'conversation.txt'
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save(False)
        self.assertIn('mes "hello";', destination.read_text(encoding='utf-8'))
        self.assertIn('emotion 3;', destination.read_text(encoding='utf-8'))
        destination = Path(self.log_folder.name) / 'dialogues.json'
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save(True)
        self.assertEqual(json.loads(destination.read_text(encoding='utf-8')), before)
        w.dialogues._issue(packet(0xb4), 99, 'Synthetic decoding error')
        panel.refresh()
        self.assertIn('解析問題 1件', panel.caption.text())
        w.dialogues.sessions.clear()
        w.dialogues.revision += 1
        panel.refresh()
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save(True)
        self.assertEqual(json.loads(destination.read_text(encoding='utf-8'))['issue_count'], 1)

    def test_basic_data_summary_inventory_export_and_reload_independence(self):
        from tests.support.player import packet, listing, pickup
        w = self.window
        self.assertIn('Zeny: 不明', w.player_panel.summary.text())
        w.add_packet(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
        w.add_packet(packet(0xb1, struct.pack('<HI', 20, 1000)))
        w.add_packet(packet(0xb08, b'\0'))
        w.add_packet(listing())
        w.add_packet(packet(0xb0b, b'\0\0'))
        w.add_packet(pickup())
        w.refresh_entity_views()
        panel = w.player_panel
        self.assertIn('test.gat', panel.summary.text())
        self.assertIn('(10, 20)', panel.summary.text())
        self.assertIn('1枠 / 合計13個（全件受信）', panel.summary.text())
        self.assertIn('Zeny: 1,000', panel.summary.text())
        panel.show_inventory()
        self.assertTrue(panel.dialog.isVisible())
        self.assertEqual(panel.items.item(0, 2).text(), '13')
        before = w.players.snapshot()
        w.reload_display()
        w.display_timestamps.setChecked(True)
        self.assertEqual(w.players.snapshot(), before)
        destination = Path(self.log_folder.name) / 'player.json'
        with patch('gui.player.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
            self.wait_display_export()
        result = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(result['states'][0]['total_amount'], 13)
        self.assertEqual(result['states'][0]['evidence']['item_gain']['packet_index'], 5)
        w.add_packet(packet(0xb08, b'\0'))
        w.add_packet(listing(items=((132, 1751, 601),), item_type=10))
        w.add_packet(listing(0xb39, items=((132, 1751, 1),), item_type=10))
        w.add_packet(packet(0xb0b, b'\0\0'))
        w.add_packet(packet(0x7fa, struct.pack('<HHH', 0, 132, 1)))
        w.refresh_entity_views()
        panel.show_inventory()
        self.assertIn('1枠 / 合計600個（全件受信）', panel.summary.text())
        self.assertEqual(panel.items.item(0, 2).text(), '600')
        self.assertEqual(w.players.issue_count, 0)

    def test_basic_data_connections_and_capture_generations_do_not_mix(self):
        from tests.support.player import packet
        w = self.window
        w.add_packet(packet(0xb1, struct.pack('<HI', 20, 1000)))
        w.add_packet(packet(0xb0, struct.pack('<HI', 5, 200), flow='other'))
        w.refresh_entity_views()
        panel = w.player_panel
        self.assertEqual(panel.selection.count(), 2)
        self.assertIn('Zeny: 不明', panel.summary.text())
        panel.selection.setCurrentIndex(0)
        panel.choose()
        self.assertIn('Zeny: 1,000', panel.summary.text())
        w.players.begin_capture(1)
        w.refresh_entity_views()
        self.assertIn('Zeny: 不明', panel.summary.text())

    def test_skill_db_name_uses_monster_and_skill_names_in_editor(self):
        from copy import deepcopy
        from tests.support.skills import mob,damage
        from reconstruction.mob_skill_export import build_candidates
        from gui.mob_skill_editor import MobSkillEditor
        w=self.window
        w.add_packet(mob());w.add_packet(damage(level=3))
        snapshot=deepcopy(w.skills.snapshot())
        for row in snapshot['observations']:row['name']='ポリン'
        name='スキル名'*30
        candidate=build_candidates(snapshot,{177:name})['candidates'][0]
        editor=MobSkillEditor(candidate,{},w)
        self.assertEqual(editor.fields['NAME'].text(),'ポリン＠'+name)
        self.assertEqual(editor.fields['NAME'].maxLength(),256)
        self.assertTrue(editor.evidence.isReadOnly())
        self.assertTrue(editor.evidence.toPlainText())
        for key in ('STATE','RATE','CASTTIME','DELAY','CANCEL','TARGET','CONDITION'):
            widget=editor.fields[key]
            if hasattr(widget,'currentData'):
                self.assertEqual(widget.currentData(),'')
            else:
                self.assertEqual(widget.text(),'')
        editor.close()

    def test_skill_hp_percent_reference_and_manual_comparison_do_not_infer_conditions(self):
        from copy import deepcopy
        from tests.support.skills import mob,damage,cast
        from tests.support.world import packet
        from reconstruction.mob_skill_export import build_candidates
        w=self.window
        events=(mob(42),mob(43),packet(0xa36,struct.pack('<IB',42,12),timestamp=.5),
            packet(0xa36,struct.pack('<IB',43,2),timestamp=.6),cast(timestamp=1),
            damage(timestamp=2,level=3),packet(0xa36,struct.pack('<IB',42,5),timestamp=2.1),
            damage(timestamp=3,tick=2000,level=3),packet(0xa36,struct.pack('<IB',42,255),timestamp=3.1),
            damage(timestamp=4,tick=3000,level=3),packet(0xa36,struct.pack('<IB',42,0),timestamp=4.1))
        for event in events:w.add_packet(event)
        w.refresh_entity_views()
        panel=w.mob_skills_panel;panel.table.selectRow(0);view=panel.notifications
        before=deepcopy((w.skills.snapshot(),w.combat.snapshot()))
        self.assertEqual([view.table.item(i,7).text() for i in range(4)],['60%','60%','25%','未取得／要確認'])
        self.assertEqual(view.hp_contexts[2]['age_ms'],900)
        view.hp_relation.setCurrentIndex(view.hp_relation.findData('le'))
        self.assertEqual([view.table.item(i,9).text() for i in range(4)],
            ['通知値では非該当','通知値では非該当','通知値では該当','未判定'])
        view.hp_relation.setCurrentIndex(view.hp_relation.findData('ge'))
        self.assertEqual(view.table.item(0,9).text(),'通知値では該当')
        self.assertEqual(view.table.item(2,9).text(),'通知値では非該当')
        view.table.selectRow(2)
        with patch.object(panel,'on_source') as source:view.hp_source.click();view.source_button.click()
        self.assertEqual([c.args[0] for c in source.call_args_list],[6,7])
        self.assertIsNone(build_candidates(w.skills.snapshot())['candidates'][0]['db_fields']['CONDITION'])
        self.assertEqual((w.skills.snapshot(),w.combat.snapshot()),before)
        # A class roundtrip cannot reuse an old same-class percentage.
        for event in (packet(0xa36,struct.pack('<IB',42,10),timestamp=4.2),
                      packet(0x1b0,struct.pack('<IBI',42,0,1006),timestamp=4.3),
                      packet(0x1b0,struct.pack('<IBI',42,0,1005),timestamp=4.4),
                      damage(timestamp=5,tick=4000,level=3)):
            w.add_packet(event)
        panel.refresh()
        self.assertEqual(view.table.item(4,7).text(),'class変更後は未取得')
        self.assertEqual(view.table.item(4,9).text(),'未判定')
        panel.scope.setCurrentIndex(1);panel.set_entity(None)
        self.assertEqual(view.hp_contexts,[])
        self.assertFalse(view.hp_source.isEnabled())
        with patch.object(panel,'on_source') as source:view.jump_hp()
        source.assert_not_called()

    def test_skill_notifications_distinguish_raw_levels_targets_and_selected_individual(self):
        from copy import deepcopy
        from tests.support.skills import mob,cast,damage
        from tests.support.world import packet
        w=self.window
        for event in (mob(42),mob(43),cast(),damage(level=3),damage(actor=43,level=0,timestamp=1.1),
                      packet(0x11a,struct.pack('<HhIIB',177,100,99,42,1),timestamp=1.2)):
            w.add_packet(event)
        w.refresh_entity_views()
        panel=w.mob_skills_panel
        panel.table.selectRow(0)
        view=panel.notifications
        before=deepcopy(w.skills.snapshot())
        self.assertEqual(view.table.rowCount(),4)
        self.assertEqual([view.table.item(i,4).text() for i in range(4)],['未通知','3','不明 (raw 0)','未通知'])
        self.assertIn('他対象（未分類） ID 99',view.table.item(1,3).text())
        self.assertIn('damage=50',view.table.item(1,5).text())
        view.table.selectRow(2)
        with patch.object(panel,'on_source') as source:view.source_button.click()
        source.assert_called_once_with(4)
        key=next(e.key for e in w.world.records('MOB') if e.actor_id==42)
        panel.scope.setCurrentIndex(1);panel.set_entity(key);panel.table.selectRow(0)
        self.assertEqual(view.table.rowCount(),3)
        self.assertTrue(all(row['actor_id']==42 for row in view.rows))
        panel.set_entity(None)
        self.assertEqual(view.table.rowCount(),0)
        self.assertFalse(view.source_button.isEnabled())
        with patch.object(panel,'on_source') as source:view.jump()
        source.assert_not_called()
        self.assertEqual(w.skills.snapshot(),before)

    def test_mob_interval_paging_preserves_full_statistics_and_original_packet_indices(self):
        from copy import deepcopy
        from tests.support.skills import mob,damage
        from tests.support.combat import attack
        w=self.window;w.add_packet(mob())
        # Populate the semantic stores directly: this tests rendering, not database throughput.
        for index in range(1003):
            w.skills.apply(damage(tick=(index+1)*1000,timestamp=index+1,level=3),packet_index=index*2+1)
            w.combat.apply(attack(tick=(index+1)*1000,timestamp=index+1),packet_index=index*2+2)
        before=deepcopy((w.skills.snapshot(),w.combat.snapshot()))
        for panel,first,last in ((w.mob_skills_panel,1,3),(w.mob_performance_panel,2,4)):
            panel.refresh();panel.table.selectRow(0)
            self.assertEqual(len(panel.interval_pager.rows),1002)
            self.assertEqual(panel.interval_table.rowCount(),2)
            self.assertTrue(panel.interval_pager.previous.isEnabled())
            panel.interval_pager.previous.click()
            self.assertEqual(panel.interval_table.rowCount(),1000)
            panel.interval_table.selectRow(0)
            with patch.object(panel,'on_source') as source:
                panel.jump_interval('from_packet_index');panel.jump_interval('packet_index')
            self.assertEqual([c.args[0] for c in source.call_args_list],[first,last])
            panel.rebuild()
            self.assertEqual(panel.interval_pager.page,0)
            preview=json.loads(panel.detail.toPlainText().split('根拠JSON:\n',1)[1])
            self.assertTrue(preview['preview_omissions'])
            self.assertLessEqual(len(preview['observations']),1000)
            if panel is w.mob_skills_panel:
                self.assertEqual(preview['summary']['intervals']['server_tick_damage']['count'],1002)
                self.assertEqual(len(preview['summary']['intervals']['server_tick_damage']['samples']),1000)
            else:
                self.assertEqual(preview['summary']['outgoing_tick_interval']['count'],1002)
                self.assertEqual(len(preview['summary']['outgoing_tick_interval']['samples']),1000)
            panel.scope.setCurrentIndex(1);panel.set_entity(None)
            self.assertEqual(panel.interval_table.rowCount(),0)
            self.assertFalse(panel.interval_pager.previous.isEnabled());self.assertFalse(panel.interval_pager.next.isEnabled())
        self.assertEqual((w.skills.snapshot(),w.combat.snapshot()),before)

    def test_skill_notification_display_limit_keeps_complete_export_and_selection(self):
        from copy import deepcopy
        from tests.support.skills import mob,damage
        w=self.window
        w.add_packet(mob());w.add_packet(damage(level=3))
        base=deepcopy(w.skills.events[0])
        records=[dict(deepcopy(base),packet_index=index) for index in range(1005)]
        w.skills.events=records
        w.skills.buckets={(tuple(base['entity_key']),base['class_id'],base['skill_id']):records}
        w.skills.revision+=1
        panel=w.mob_skills_panel;panel.refresh();panel.table.selectRow(0)
        view=panel.notifications
        self.assertEqual(view.table.rowCount(),1000)
        self.assertEqual(view.rows[0]['packet_index'],5)
        preview=json.loads(panel.detail.toPlainText().split('根拠JSON:\n',1)[1])
        self.assertEqual(preview['observation_count'],1005)
        self.assertEqual(len(preview['observations']),1000)
        self.assertEqual(preview['omitted_from_preview'],5)
        view.table.selectRow(0);panel.rebuild()
        self.assertEqual(view.selected()['packet_index'],5)
        before=deepcopy(w.skills.snapshot())
        destination=Path(self.log_folder.name)/'skills-complete.json'
        with patch('gui.skills.QFileDialog.getSaveFileName',return_value=(str(destination),'')):
            panel.save()
            self.wait_display_export()
        self.assertEqual(len(json.loads(destination.read_text(encoding='utf-8'))['observations']),1005)
        self.assertEqual(w.skills.snapshot(),before)

    def test_mob_skill_summary_selection_source_export_and_widget_lifetime(self):
        import gc
        from tests.support.skills import mob, damage
        w = self.window
        w.add_packet(mob())
        w.add_packet(damage())
        w.add_packet(damage(tick=6000, timestamp=6))
        gc.collect()
        self.app.processEvents()
        w.refresh_entity_views()
        panel = w.mob_skills_panel
        self.assertEqual(w.mob_panel.details_tabs.tabText(1), '使用スキル')
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.table.item(0, 2).text(), 'ブラインドアタック')
        self.assertEqual(panel.table.item(0, 7).text(), '不明')
        self.assertEqual(panel.table.item(0, 8).text(), '5000')
        panel.table.selectRow(0)
        self.assertIn('65535', panel.detail.toPlainText())
        panel.jump()
        self.assertEqual(w.table.currentRow(), 2)
        before = w.skills.snapshot()
        w.reload_display()
        self.assertEqual(w.skills.snapshot(), before)
        w.mob_panel.table.setCurrentIndex(w.mob_panel.model.index(0, 0))
        panel.scope.setCurrentIndex(1)
        self.assertEqual(panel.table.rowCount(), 1)
        destination = Path(self.log_folder.name) / 'skills.json'
        with patch('gui.skills.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
            self.wait_display_export()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(saved['class_skills'][0]['counts']['damage'], 2)
        self.assertEqual(len(saved['observations']), 2)
        destination = Path(self.log_folder.name) / 'mob-skill-review.txt'
        with patch('gui.skills.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save_candidates()
        self.assertTrue(all(line.startswith('//') for line in destination.read_text(encoding='utf-8').splitlines()))
        self.assertEqual(w.skills.snapshot(), before)
        destination = destination.with_suffix('.json')
        with patch('gui.skills.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save_candidates()
        review = json.loads(destination.read_text(encoding='utf-8'))
        self.assertIsNone(review['candidates'][0]['db_fields']['DELAY'])
        self.assertFalse(review['active_db_rows_generated'])
        from gui.mob_skill_editor import MobSkillEditor
        from reconstruction.mob_skill_export import COLUMNS
        from PySide6.QtWidgets import QComboBox
        editor = MobSkillEditor(review['candidates'][0], {0: 'capture.jsonl'}, panel)
        self.assertIsNot(editor.candidate, review['candidates'][0])
        original_delay = editor.candidate['db_fields']['DELAY']
        review['candidates'][0]['db_fields']['DELAY'] = 12345
        self.assertEqual(editor.candidate['db_fields']['DELAY'], original_delay)
        self.assertEqual(editor.fields['DELAY'].text(), '')
        with self.assertRaises(ValueError):
            editor.document()
        manual = dict.fromkeys(COLUMNS, '0')
        manual.update(MOB_ID='1005', NAME='test_only', STATE='attack', SKILL_ID='177',
                      SKILL_LV='5', RATE='1000', CASTTIME='500', DELAY='6000',
                      CANCEL='no', TARGET='target', CONDITION='always')
        for key, value in manual.items():
            widget = editor.fields[key]
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            else:
                widget.setText(value)
        editor.confirmed.setChecked(True)
        configured_path = Path(self.log_folder.name) / 'configured.json'
        with patch('gui.mob_skill_editor.QFileDialog.getSaveFileName', return_value=(str(configured_path), '')):
            editor.save()
        configured = json.loads(configured_path.read_text(encoding='utf-8'))
        self.assertEqual(configured['db_fields']['DELAY'], 6000)
        self.assertTrue(configured['active_db_row_generated'])
        self.assertIsNone(configured['observation']['db_fields']['DELAY'])
        editor.generate()
        self.assertIn(configured['db_row'], editor.preview.toPlainText())
        condition = editor.fields['CONDITION']
        condition.setCurrentIndex(condition.findData('mystatuson'))
        self.assertFalse(editor.confirmed.isChecked())
        self.assertEqual(editor.preview.toPlainText(), '')
        self.assertIn('poison', editor.condition_note.text())
        self.assertEqual(editor.fields['CONDITION_VALUE'].text(), '0')
        with self.assertRaises(ValueError):
            editor.document()
        editor.fields['CONDITION_VALUE'].setText('poison')
        editor.confirmed.setChecked(True)
        with patch('gui.mob_skill_editor.QFileDialog.getSaveFileName', return_value=(str(configured_path), '')):
            editor.save()
        configured = json.loads(configured_path.read_text(encoding='utf-8'))
        self.assertEqual(configured['db_fields']['CONDITION_VALUE'], 'poison')
        condition.setCurrentIndex(condition.findData('myhpltmaxrate'))
        self.assertIn('16bit', editor.condition_note.text())
        with self.assertRaises(ValueError):
            editor.document()
        editor.fields['CONDITION_VALUE'].setText('50')
        self.assertFalse(editor.confirmed.isChecked())
        editor.confirmed.setChecked(True)
        self.assertEqual(editor.document()['db_fields']['CONDITION_VALUE'], 50)
        with patch('gui.mob_skill_editor.QFileDialog.getOpenFileName', return_value=(str(configured_path), '')):
            editor.load()
        self.assertEqual(condition.currentData(), 'mystatuson')
        self.assertEqual(editor.fields['CONDITION_VALUE'].text(), 'poison')
        self.assertFalse(editor.confirmed.isChecked())
        with self.assertRaises(ValueError):
            editor.document()
        editor.confirmed.setChecked(True)
        before_load = editor.document()
        configured_path.write_text('{}', encoding='utf-8')
        with patch('gui.mob_skill_editor.QFileDialog.getOpenFileName', return_value=(str(configured_path), '')), \
             patch('gui.mob_skill_editor.QMessageBox.warning') as warning:
            editor.load()
        warning.assert_called_once()
        self.assertEqual(editor.document(), before_load)
        text_path = configured_path.with_suffix('.txt')
        with patch('gui.mob_skill_editor.QFileDialog.getSaveFileName', return_value=(str(text_path), '')):
            editor.save()
        active_rows = [line for line in text_path.read_text(encoding='utf-8').splitlines()
                       if not line.startswith('//')]
        self.assertEqual(active_rows, [before_load['db_row']])
        self.assertEqual(active_rows[0].split(',')[-1], '00')
        original_bytes = text_path.read_bytes()
        with patch('gui.mob_skill_editor.QFileDialog.getSaveFileName', return_value=(str(text_path), '')), \
                patch('gui.mob_skill_editor.os.replace', side_effect=OSError('locked')), \
                patch('gui.mob_skill_editor.QMessageBox.warning') as failed_save:
            editor.save()
        failed_save.assert_called_once()
        self.assertEqual(text_path.read_bytes(), original_bytes)
        self.assertFalse(list(text_path.parent.glob(text_path.name + '.*.tmp')))
        self.assertEqual(w.skills.snapshot(), before)
        editor.close()
        editor.deleteLater()
        spawn_panel = w.mob_spawn_panel
        spawn_panel.refresh()
        self.assertEqual(spawn_panel.table.rowCount(), 1)
        spawn_panel.table.selectRow(0)
        spawn_panel.jump()
        self.assertEqual(w.table.currentRow(), 0)
        spawn_path = Path(self.log_folder.name) / 'mob-spawns.json'
        with patch('gui.mob_spawns.QFileDialog.getSaveFileName', return_value=(str(spawn_path), '')):
            spawn_panel.save()
        spawn_report = json.loads(spawn_path.read_text(encoding='utf-8'))
        self.assertEqual(spawn_report['groups'][0]['peak_tracked'], 1)
        self.assertIsNone(spawn_report['groups'][0]['configured_spawn_count'])
        spawn_review = Path(self.log_folder.name) / 'mob-spawn-review.txt'
        with patch('gui.mob_spawns.QFileDialog.getSaveFileName', return_value=(str(spawn_review), '')):
            spawn_panel.save_candidates()
        self.assertTrue(all(line.startswith('//') for line in spawn_review.read_text(encoding='utf-8').splitlines()))
        spawn_review = spawn_review.with_suffix('.json')
        with patch('gui.mob_spawns.QFileDialog.getSaveFileName', return_value=(str(spawn_review), '')):
            spawn_panel.save_candidates()
        candidate_report = json.loads(spawn_review.read_text(encoding='utf-8'))
        self.assertIsNone(candidate_report['candidates'][0]['placement_fields']['amount'])
        self.assertFalse(candidate_report['active_placements_generated'])
        self.assertEqual(json.loads(json.dumps(w.mob_spawns.snapshot())),
                         {key: value for key, value in spawn_report.items() if key != 'source_sessions'})
        from gui.mob_spawn_editor import MobSpawnEditor
        with patch('gui.mob_spawn_editor.MobSpawnEditor.exec', return_value=0) as opened:
            spawn_panel.edit_candidate()
        opened.assert_called_once()
        spawn_editor = MobSpawnEditor(candidate_report['candidates'][0], {0: 'capture.jsonl'}, spawn_panel)
        self.assertIsNot(spawn_editor.candidate, candidate_report['candidates'][0])
        previous_peak = spawn_editor.candidate['observed']['peak_tracked']
        candidate_report['candidates'][0]['observed']['peak_tracked'] = previous_peak + 100
        self.assertEqual(spawn_editor.candidate['observed']['peak_tracked'], previous_peak)
        self.assertTrue(spawn_editor.evidence.isReadOnly())
        self.assertTrue(spawn_editor.evidence.toPlainText())
        self.assertEqual(spawn_editor.fields['x'].text(), '')
        self.assertEqual(spawn_editor.fields['amount'].text(), '')
        self.assertEqual(spawn_editor.fields['delay1'].text(), '')
        self.assertEqual(spawn_editor.fields['delay2'].text(), '')
        with self.assertRaises(ValueError):
            spawn_editor.document()
        manual = dict(map_name='prontera', x='150', y='200', xs='0', ys='0', mob_name='test_only',
                      class_id='1005', amount='1', delay1='5000', delay2='0', event='')
        for key, value in manual.items():
            spawn_editor.fields[key].setText(value)
        spawn_editor.confirmed.setChecked(True)
        configured_spawn = Path(self.log_folder.name) / 'spawn-configured.json'
        with patch('gui.mob_spawn_editor.QFileDialog.getSaveFileName', return_value=(str(configured_spawn), '')):
            spawn_editor.save()
        configured = json.loads(configured_spawn.read_text(encoding='utf-8'))
        self.assertTrue(configured['active_placement_generated'])
        self.assertEqual(configured['placement_fields']['delay1'], 5000)
        self.assertIsNone(configured['observation']['placement_fields']['delay1'])
        spawn_editor.generate()
        self.assertIn(configured['placement_row'], spawn_editor.preview.toPlainText())
        spawn_editor.fields['amount'].setText('2')
        self.assertFalse(spawn_editor.confirmed.isChecked())
        self.assertEqual(spawn_editor.preview.toPlainText(), '')
        with patch('gui.mob_spawn_editor.QFileDialog.getOpenFileName', return_value=(str(configured_spawn), '')):
            spawn_editor.load()
        self.assertEqual(spawn_editor.fields['amount'].text(), '1')
        self.assertFalse(spawn_editor.confirmed.isChecked())
        with self.assertRaises(ValueError):
            spawn_editor.document()
        spawn_editor.confirmed.setChecked(True)
        configured_text = Path(self.log_folder.name) / 'spawn-configured.txt'
        with patch('gui.mob_spawn_editor.QFileDialog.getSaveFileName', return_value=(str(configured_text), '')):
            spawn_editor.save(as_text=True)
        self.assertEqual([row for row in configured_text.read_text(encoding='utf-8').splitlines()
                          if not row.startswith('//')], [configured['placement_row']])
        old_text = configured_text.read_bytes()
        with patch('gui.mob_spawn_editor.QFileDialog.getSaveFileName', return_value=(str(configured_text), '')), \
                patch('gui.mob_spawn_editor.os.replace', side_effect=OSError('locked')), \
                patch('gui.mob_spawn_editor.QMessageBox.warning') as failed_save:
            spawn_editor.save(as_text=True)
        failed_save.assert_called_once()
        self.assertEqual(configured_text.read_bytes(), old_text)
        self.assertFalse(list(configured_text.parent.glob(configured_text.name + '.*.tmp')))
        altered = dict(configured, placement_row='wrong')
        configured_spawn.write_text(json.dumps(altered), encoding='utf-8')
        with patch('gui.mob_spawn_editor.QFileDialog.getOpenFileName', return_value=(str(configured_spawn), '')), \
                patch('gui.mob_spawn_editor.QMessageBox.warning') as warning:
            spawn_editor.load()
        warning.assert_called_once()
        self.assertEqual(spawn_editor.fields['amount'].text(), '1')
        self.assertEqual(json.loads(json.dumps(w.mob_spawns.snapshot())),
                         {key: value for key, value in spawn_report.items() if key != 'source_sessions'})
        spawn_editor.close()
        spawn_editor.deleteLater()

    def test_mob_skill_name_reload_keeps_statistics_and_last_good_dictionary(self):
        from tests.support.skills import mob, damage
        w = self.window
        w.add_packet(mob())
        w.add_packet(damage())
        w.refresh_entity_views()
        panel = w.mob_skills_panel
        before = w.skills.snapshot()
        with patch('gui.skills.load_skill_names_with_hash', return_value=({177:'custom skill'},'0'*64)):
            panel.reload_names()
        self.assertEqual(panel.table.item(0, 2).text(), 'custom skill')
        with patch('gui.skills.load_skill_names_with_hash', side_effect=ValueError('Invalid dictionary')):
            panel.reload_names()
        self.assertEqual(panel.names[177], 'custom skill')
        self.assertEqual(w.skills.snapshot(), before)

    def test_performance_individual_comparison_separates_servers_reappearances_and_quality(self):
        from copy import deepcopy
        from tests.support.skills import mob
        from tests.support.combat import attack
        from tests.support.world import packet
        w=self.window
        first=str(('10.0.0.2',5121,'192.0.2.1',50000))
        second=str(('10.0.0.10',5121,'192.0.2.1',50001))
        events=(mob(42,connection=first),mob(142,connection=second),
            attack(actor=42,connection=first,tick=1000,timestamp=1),
            attack(actor=42,connection=first,tick=1500,timestamp=2,damage=20),
            attack(actor=142,connection=second,tick=5000,timestamp=3,damage=80),
            packet(0x977,struct.pack('<Iii',42,90,100),connection=first,timestamp=4),
            packet(0x977,struct.pack('<Iii',42,120,100),connection=first,timestamp=5),
            packet(0x80,struct.pack('<IB',42,0),connection=first,timestamp=6),
            mob(42,connection=first,timestamp=7),
            attack(actor=42,connection=first,tick=30000,timestamp=8,damage=30))
        for event in events:w.add_packet(event)
        w.refresh_entity_views()
        panel=w.mob_performance_panel;panel.table.selectRow(0);view=panel.individuals
        before=deepcopy(w.combat.snapshot())
        self.assertEqual([(r['entity_key'][3],r['entity_key'][4]) for r in view.rows],[(42,1),(42,2),(142,1)])
        self.assertEqual(view.rows[0]['min_hp_tick_ms'],500)
        self.assertIsNone(view.rows[1]['min_hp_tick_ms'])
        self.assertEqual(view.rows[0]['max_hp'],[100])
        self.assertEqual(view.rows[0]['quality_records'],1)
        self.assertEqual(view.rows[0]['quality_flags'],{'hp_exceeds_max':1})
        self.assertEqual(view.rows[2]['outgoing_hp']['min'],80)
        view.table.selectRow(0)
        with patch.object(panel,'on_source') as source:
            view.first.click();view.last.click()
        self.assertEqual([call.args[0] for call in source.call_args_list],[0,6])
        selected=view.selected_key();panel.rebuild()
        self.assertEqual(view.selected_key(),selected)
        second_key=tuple(view.rows[1]['entity_key'])
        panel.scope.setCurrentIndex(1);panel.set_entity(second_key);panel.table.selectRow(0)
        self.assertEqual(len(view.rows),1)
        self.assertEqual(view.rows[0]['entity_key'][4],2)
        panel.set_entity(None)
        self.assertEqual(view.table.rowCount(),0)
        self.assertFalse(view.first.isEnabled());self.assertFalse(view.last.isEnabled())
        with patch.object(panel,'on_source') as source:view.jump('last_packet_index')
        source.assert_not_called()
        self.assertEqual(w.combat.snapshot(),before)

    def test_performance_individual_comparison_limits_rows_without_altering_summaries(self):
        from copy import deepcopy
        from tests.support.skills import mob
        w=self.window;w.add_packet(mob());w.refresh_entity_views()
        panel=w.mob_performance_panel
        summary=w.combat.summaries()[0]
        summaries=[]
        for actor in range(1005):
            row=deepcopy(summary);row['entity_key']=(0,'unknown',0,actor,1)
            summaries.append(row)
        before=deepcopy(summaries)
        view=panel.individuals
        view.set_summaries(list(reversed(summaries)),w.world,[])
        self.assertEqual(view.table.rowCount(),1000)
        self.assertEqual(view.rows[0]['entity_key'][3],0)
        self.assertEqual(view.rows[-1]['entity_key'][3],999)
        self.assertIn('1005',view.caption.text())
        self.assertEqual(summaries,before)

    def test_mob_performance_table_source_export_and_display_reload(self):
        from tests.support.skills import mob
        from tests.support.combat import attack
        w = self.window
        w.add_packet(mob())
        w.add_packet(attack(damage=10, left=2))
        w.add_packet(attack(damage=20, tick=6000, timestamp=6))
        w.refresh_entity_views()
        self.app.processEvents()
        panel = w.mob_performance_panel
        self.assertEqual(w.mob_panel.details_tabs.tabText(2), '性能観測')
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.table.item(0, 3).text(), '150')
        self.assertEqual(panel.table.item(0, 4).text(), '未取得')
        self.assertEqual(panel.table.item(0, 5).text(), '12～20')
        self.assertEqual(panel.table.item(0, 7).text(), '5000')
        panel.table.selectRow(0)
        self.assertIn('元のATK／DEFは算出していません', panel.detail.toPlainText())
        panel.jump()
        self.assertEqual(w.table.currentRow(), 2)
        before = w.combat.snapshot()
        w.reload_display()
        self.assertEqual(w.combat.snapshot(), before)
        destination = Path(self.log_folder.name) / 'performance.json'
        with patch('gui.combat.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save()
            self.wait_display_export()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(saved['class_performance'][0]['counts']['outgoing'], 2)
        self.assertEqual(saved['attack_packet_count'], 2)

    def test_mob_performance_selected_entity_and_capture_boundaries(self):
        from tests.support.skills import mob
        from tests.support.combat import attack
        w = self.window
        w.add_packet(mob())
        w.add_packet(mob(43))
        w.add_packet(attack())
        w.add_packet(attack(actor=43, tick=1100, timestamp=1.1))
        w.refresh_entity_views()
        panel = w.mob_performance_panel
        w.mob_panel.table.setCurrentIndex(w.mob_panel.model.index(0, 0))
        panel.scope.setCurrentIndex(1)
        self.assertEqual(panel.rows[0]['counts']['outgoing'], 1)
        self.assertEqual(panel.rows[0]['source_appearances'], 1)
        self.assertIsNone(panel.rows[0]['outgoing_tick_interval']['min'])
        w.mob_panel.table.setCurrentIndex(w.mob_panel.model.index(1, 0))
        self.assertEqual(panel.rows[0]['entity_key'][3], 43)

    def test_merged_dialogue_preview_and_exports_preserve_single_path(self):
        from tests.support.branches import conversation
        w = self.window
        first, second = conversation(), conversation(2, 'two result', identifier=2)
        w.dialogues.sessions = [first, second]
        w.dialogues.revision += 1
        w.refresh_entity_views()
        panel = w.dialogue_panel
        single_code = panel.code.toPlainText()
        panel.merge_checkbox.setChecked(True)
        self.assertIn('2会話', panel.merge_status.text())
        self.assertIn('mes "one result";', panel.code.toPlainText())
        self.assertIn('mes "two result";', panel.code.toPlainText())
        destination = Path(self.log_folder.name) / 'merged.txt'
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save(False)
        self.assertIn('two result', destination.read_text(encoding='utf-8'))
        destination = Path(self.log_folder.name) / 'merged.json'
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save_merged()
        report = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(len(report['groups'][0]['contributions']), 2)
        panel.merge_checkbox.setChecked(False)
        self.assertEqual(panel.code.toPlainText(), single_code)
        npc_destination = Path(self.log_folder.name) / 'placed-npc.txt'
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(npc_destination), '')):
            panel.save_npc_file()
        self.assertIn('test.gat,10,20,0\tscript\t案内人\t45,{/*', npc_destination.read_text(encoding='utf-8'))
        panel.merge_checkbox.setChecked(True)
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(npc_destination), '')):
            panel.save_npc_file()
        self.assertIn('two result', npc_destination.read_text(encoding='utf-8'))
        panel.merge_checkbox.setChecked(False)
        # Repeating the same choice with an extra effect must warn in both views.
        import copy
        repeated = copy.deepcopy(first)
        repeated.id = 3
        step = copy.deepcopy(repeated.steps[-1])
        step.update(kind='effect', fields=dict(value=99))
        repeated.steps.insert(-1, step)
        w.dialogues.sessions = [first, repeated]
        w.dialogues.revision += 1
        panel.refresh()
        self.assertIn('演出不一致 1経路', panel.merge_status.text())
        self.assertIn('要確認', panel.code.toPlainText())
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save(False)
        self.assertIn('要確認', destination.read_text(encoding='utf-8'))
        panel.merge_checkbox.setChecked(True)
        self.assertIn('演出不一致 1経路', panel.merge_status.text())
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save_merged()
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(saved['groups'][0]['presentation_check']['conflicts'], 1)

    def test_merged_dialogue_rejects_incomplete_identity_and_refreshes_after_new_path(self):
        from tests.support.branches import conversation
        w = self.window
        first = conversation()
        first.npc = {}
        w.dialogues.sessions = [first]
        w.dialogues.revision += 1
        w.refresh_entity_views()
        panel = w.dialogue_panel
        panel.merge_checkbox.setChecked(True)
        self.assertIn('統合できません', panel.code.toPlainText())
        w.dialogues.sessions = [conversation(), conversation(2, 'new branch', identifier=2)]
        w.dialogues.revision += 1
        w.refresh_entity_views()
        self.assertIn('new branch', panel.code.toPlainText())

    def test_input_response_comments_and_continuation_are_shown_and_saved(self):
        from tests.support.dialogue import packet
        from dataclasses import replace
        w = self.window
        w.add_packet(replace(actor_packet(), connection='half', flow_id='flow'))
        w.add_packet(packet(0x90, struct.pack('<IB', 42, 1), 'SEND'))
        w.add_packet(packet(0x142, struct.pack('<I', 42)))
        w.add_packet(packet(0x143, struct.pack('<Ii', 42, -3), 'SEND'))
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'after input\0'))
        w.add_packet(packet(0xb6, struct.pack('<I', 42)))
        w.refresh_entity_views()
        panel = w.dialogue_panel
        self.assertIn('// 入力数: -3\n{\n    mes "after input";', panel.code.toPlainText())
        panel.merge_checkbox.setChecked(True)
        self.assertIn('// 入力数: -3\n{\n    mes "after input";', panel.code.toPlainText())
        destination = Path(self.log_folder.name) / 'input-response.txt'
        with patch('gui.dialogues.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            panel.save(False)
        self.assertIn('入力数: -3', destination.read_text(encoding='utf-8'))

    def test_timeline_table_wait_duration_and_selected_source(self):
        from tests.support.dialogue import packet
        w = self.window
        w.add_packet(packet(0x90, struct.pack('<IB', 42, 1), 'SEND', timestamp=0))
        w.add_packet(packet(0xb5, struct.pack('<I', 42), timestamp=1))
        w.add_packet(packet(0x1b3, b'image'.ljust(64, b'\0') + b'\0', timestamp=2))
        w.add_packet(packet(0xb9, struct.pack('<I', 42), 'SEND', timestamp=4))
        w.refresh_entity_views()
        panel = w.dialogue_panel
        self.assertEqual(panel.timeline.rowCount(), 4)
        self.assertIn('input_wait', panel.presentations.toPlainText())
        self.assertIn('cutin', panel.presentations.toPlainText())
        self.assertEqual(panel.timeline.item(3, 1).text(), '2000')
        self.assertEqual(panel.timeline.item(3, 2).text(), '3000')
        panel.timeline.selectRow(3)
        panel.jump()
        self.assertEqual(w.table.currentRow(), 3)
        self.assertIn('timelines', w.dialogues.snapshot())

    def test_incomplete_spawn_name_is_labelled_reference_only_and_recovers(self):
        from dataclasses import replace
        data=bytes.fromhex('23835283938370835870726f5f61735f837a838d839390')
        raw=bytearray(actor_packet(raw_name=data).raw[:-1])
        struct.pack_into('<H',raw,2,len(raw))
        w=self.window
        w.add_packet(map_packet())
        w.add_packet(replace(actor_packet(),raw=bytes(raw)))
        w.refresh_entity_views()
        panel=w.npc_panel
        panel.table.setCurrentIndex(panel.model.index(0,0))
        self.assertIn('不完全名・参考',panel.model.data(panel.model.index(0,0)))
        self.assertIn('確定名へ採用しません',panel.detail.toPlainText())
        self.assertIn(data.hex(),panel.detail.toPlainText())
        self.assertEqual(w.world.records('NPC')[0].name,'')
        w.add_packet(name_packet(name='正式名'))
        w.refresh_entity_views()
        self.assertEqual(panel.model.data(panel.model.index(0,0)),'正式名')
        self.assertNotIn('参考接頭部分',panel.detail.toPlainText())
        self.assertEqual(w.world.records('NPC')[0].name,'正式名')

    def test_npc_and_mob_views_use_semantic_state_and_export_evidence(self):
        w = self.window
        w.add_packet(map_packet())
        w.add_packet(actor_packet())
        w.add_packet(actor_packet(actor_id=43, actor_type=5, name='モンスター'))
        w.refresh_entity_views()
        self.assertEqual(w.npc_panel.model.rowCount(), 1)
        self.assertEqual(w.mob_panel.model.rowCount(), 1)
        self.assertEqual(w.npc_panel.model.data(w.npc_panel.model.index(0, 0)), '案内人')
        w.npc_panel.table.setCurrentIndex(w.npc_panel.model.index(0, 0))
        self.assertIn('0x09FF', w.npc_panel.detail.toPlainText())
        w.add_packet(name_packet())
        w.refresh_entity_views()
        self.assertEqual(w.npc_panel.model.data(w.npc_panel.table.currentIndex()), '正式名')
        self.assertIn('0x0ADF', w.npc_panel.detail.toPlainText())
        output = Path(self.log_folder.name) / 'npc.json'
        with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(output), '')):
            w.save_entities('NPC')
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(len(result['entities']), 1)
        self.assertEqual(result['entities'][0]['map_name'], 'prontera.gat')
        self.assertEqual(result['entities'][0]['evidence'][-1]['packet_id'], 0xadf)
        w.filter.setText('FFFF')
        w.npc_panel.source_button.click()
        self.assertIs(w.workspace_tabs.currentWidget(), w.packet_page)
        self.assertEqual(w.table.currentRow(), 3)
        self.assertEqual(w.filter.text(), '')
        self.assertIn('0x0ADF', w.hex.toPlainText())

    def test_entity_active_filter_and_display_reload_do_not_rebuild_world(self):
        w = self.window
        w.add_packet(actor_packet())
        w.refresh_entity_views()
        original = w.world.records()[0]
        w.reload_display()
        self.assertIs(w.world.records()[0], original)
        self.assertEqual(original.observations, 1)
        w.add_packet(event(0x80, struct.pack('<IB', 42, 0), connection='flow-a'))
        w.refresh_entity_views()
        self.assertEqual(w.npc_panel.model.rowCount(), 1)
        w.npc_panel.active_only.setChecked(True)
        self.assertEqual(w.npc_panel.model.rowCount(), 0)
        w.npc_panel.active_only.setChecked(False)
        self.assertEqual(w.npc_panel.model.rowCount(), 1)

    def test_partial_entity_decode_retains_table_data_and_diagnostic(self):
        w = self.window
        w.add_packet(actor_packet(raw_name=b'\x81'))
        w.refresh_entity_views()
        self.assertEqual(w.npc_panel.model.rowCount(), 1)
        self.assertEqual(w.npc_panel.model.data(w.npc_panel.model.index(0, 0)), '未取得')
        self.assertEqual(w.world.issue_count, 1)
        self.assertIn('Entity observation failed', w.capture_log.toPlainText())
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 1)
