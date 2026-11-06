import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from tests.support.qt import install_offscreen_qt_message_filter
install_offscreen_qt_message_filter()
from parser.display import DEFAULT_PROFILE
from tests.support.display import event, variable
from tests.support.world import actor_packet, packet as timed_packet
import struct



from tests.support.qt import WindowTestCase


class DisplayGuiTests(WindowTestCase):
    def test_effect_reference_symbols_do_not_create_status_or_dialogue_commands(self):
        from tests.support.display import event
        import struct
        w=self.window
        effect=event(0x19b,struct.pack('<II',42,12))
        status=event(0x196,struct.pack('<HIB',12,42,1))
        w.add_packet(effect);w.add_packet(status)
        self.assertIn('EF_BEGINSPELL',w.display_log.toPlainText())
        self.assertIn('status_icon: EFST_',w.display_log.toPlainText())
        self.assertEqual(w.events[-2:],[effect,status])
        self.assertFalse(w.dialogues.sessions)
        self.assertFalse(w.skills.events)

    def test_skill_unit_labels_do_not_create_mob_skill_uses_or_change_actor_identity(self):
        from tests.support.skills import mob,unit_appearance
        w=self.window
        w.add_packet(mob())
        packet=unit_appearance()
        w.add_packet(packet)
        self.assertIn('UNT_FIREWALL',w.display_log.toPlainText())
        self.assertIn('ファイアーウォール',w.display_log.toPlainText())
        self.assertIn('unit_actor: 4444',w.display_log.toPlainText())
        self.assertIn('src: 42',w.display_log.toPlainText())
        self.assertEqual(w.events[-1],packet)
        self.assertFalse(w.skills.events)
        self.assertEqual([entity.actor_id for entity in w.world.records('MOB')],[42])
        self.assertFalse(w.world.records('NPC'))

    def seed_large_history(self,count=2105):
        from parser.display import DisplayResult
        w=self.window
        w.events[:]=[timed_packet(0xb5,bytes(4),timestamp=index+1) for index in range(count)]
        w.display_sessions[:]=[1]*count
        w.observation_tags[:]=[{} for _ in range(count)]
        w.display_results[:]=[DisplayResult('test','old','decoded') for _ in range(count)]
        w.capture_session=1
        w.schedule_history_view(immediate=True)

    def finish_history_update(self):
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtTest import QTest
        elapsed=QElapsedTimer();elapsed.start()
        while self.window.history_tasks.busy and elapsed.elapsed()<5000:
            self.app.processEvents();QTest.qWait(1)
        self.assertFalse(self.window.history_tasks.busy)

    def test_default_packet_lengths_use_project_root_even_when_extracted_file_exists(self):
        from gui.layout import PROJECT_ROOT
        self.assertEqual(Path(self.window.path.text()),PROJECT_ROOT/'PacketLength.txt')
        self.window.path.setText(str(PROJECT_ROOT/'client'/'PacketLength.extracted.txt'))
        self.assertEqual(Path(self.window.path.text()),PROJECT_ROOT/'client'/'PacketLength.extracted.txt')

    def test_comparison_popup_preserves_state_returns_to_tab_and_closes_with_owner(self):
        from PySide6.QtWidgets import QWidget
        from tests.support.event_trials import repeated_report
        w=self.window;panel=w.dialogue_panel.event_trials
        report=repeated_report('effect')
        panel.report=report;panel.report_key=panel.current_key();panel.show_trial_summary()
        w.show_comparison_window();self.app.processEvents()
        popup=w.comparison_dialog
        self.assertTrue(popup.isVisible())
        self.assertEqual(w.workspace_tabs.indexOf(panel),-1)
        self.assertIs(QWidget.window(panel),popup)
        self.assertIs(popup.path,w.path)
        self.assertIs(panel.report,report)
        self.assertTrue(panel.adopt_button.isEnabled())
        with patch('gui.event_trials.QFileDialog.getSaveFileName',return_value=(w.path.text(),'')),patch('gui.event_trials.QMessageBox.warning') as warning:
            panel.save()
        warning.assert_called_once()
        self.assertEqual(panel.popout_button.text(),'主画面へ戻す')
        panel.popout_button.click();self.app.processEvents()
        self.assertEqual(panel.popout_button.text(),'別ウィンドウ…')
        self.assertEqual(w.workspace_tabs.indexOf(panel),4)
        self.assertIs(panel.report,report)
        w.show_comparison_window()
        self.assertIs(w.comparison_dialog,popup)
        w.close();self.wait_window_closed()
        self.assertFalse(popup.isVisible())
        self.assertEqual(w.workspace_tabs.indexOf(panel),4)

    def test_workspace_layout_keeps_comparison_independent_and_fits_compact_window(self):
        from gui.layout import show_panel
        w=self.window
        w.resize(1024,740);w.show();self.app.processEvents()
        self.assertEqual(w.workspace_tabs.indexOf(w.dialogue_panel.event_trials),4)
        self.assertEqual(w.dialogue_panel.details_tabs.indexOf(w.dialogue_panel.event_trials),-1)
        self.assertLess(w.minimumSizeHint().height(),850)
        w.workspace_tabs.setCurrentWidget(w.dialogue_panel.event_trials)
        self.app.processEvents()
        panel=w.dialogue_panel.event_trials
        self.assertGreaterEqual(panel.table.height(),90)
        self.assertGreaterEqual(panel.events.height(),90)
        self.assertGreater(panel.trials.width(),200)
        self.assertTrue(panel.adopt_button.isVisible())
        self.assertLessEqual(panel.adopt_button.geometry().right(),panel.adopt_button.parentWidget().width())
        self.assertEqual([a.text() for a in w.menuBar().actions()],['作業','出力','設定・診断'])
        self.assertTrue(w.export_all_npcs_action.isVisible())
        w.export_conversation_action.parent().aboutToShow.emit()
        self.assertFalse(w.export_conversation_action.isEnabled())
        self.assertFalse(w.export_selected_npc_action.isEnabled())
        self.assertFalse(w.export_dialogue_json_action.isEnabled())
        w.export_merge_action.setChecked(True)
        self.assertTrue(w.dialogue_panel.merge_checkbox.isChecked())
        w.dialogue_panel.merge_checkbox.setChecked(False)
        self.assertFalse(w.export_merge_action.isChecked())
        show_panel(w.settings_dialog);self.app.processEvents()
        self.assertTrue(w.settings_dialog.isVisible())
        self.assertTrue(w.settings_dialog.property('workspaceGeometryReady'))
        w.settings_dialog.close()
        w.workspace_tabs.setCurrentWidget(w.dialogue_panel)
        self.app.processEvents()
        self.assertGreaterEqual(w.dialogue_panel.code.height(),90)
        self.assertGreaterEqual(w.dialogue_panel.details_tabs.height(),170)
        self.assertEqual(w.dialogue_panel.details_tabs.tabText(w.dialogue_panel.details_tabs.count()-1),'根拠JSON')
        w.workspace_tabs.setCurrentWidget(w.mob_panel);self.app.processEvents()
        self.assertGreater(w.mob_panel.table.height(),140)
        self.assertLess(w.mob_panel.details_tabs.minimumSizeHint().height(),200)

    def test_async_reformat_cancel_replace_and_live_append_keep_latest_complete_results(self):
        from parser.display import DisplayProfile,ReceiveDisplay
        from copy import deepcopy
        w=self.window
        self.seed_large_history()
        original=w.display_results
        w.display_timestamps.setChecked(True)
        self.assertTrue(w.history_tasks.running('format'))
        w.history_tasks.advance()
        self.assertIs(w.display_results,original)
        w.history_cancel.click()
        self.assertIs(w.display_results,original)
        self.assertFalse(w.display_timestamps.isChecked())
        document=json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        def renderer(text):
            changed=deepcopy(document)
            next(rule for rule in changed['packets'] if '00B5' in rule['ids'])['template']=text
            return ReceiveDisplay(DisplayProfile(changed))
        w._reformat_with(renderer('discarded'))
        w.history_tasks.advance()
        w._reformat_with(renderer('latest'))
        w.add_packet(timed_packet(0xb5,bytes(4),timestamp=5000))
        from PySide6.QtCore import QTimer
        heartbeats=[]
        QTimer.singleShot(0,lambda:heartbeats.append(w.history_tasks.busy))
        self.finish_history_update()
        self.assertEqual(heartbeats,[True])
        self.assertEqual(len(w.display_results),2106)
        self.assertEqual(set(result.text for result in w.display_results),{'latest'})
        self.assertNotIn('discarded',w.display_log.toPlainText())
        self.assertTrue(w.display_save.isEnabled())
        w.add_packet(timed_packet(0xb5,bytes(4),timestamp=5001))
        self.assertEqual(w.display_results[-1].text,'latest')

    def test_async_filter_supersession_cancel_and_refresh_do_not_mix_old_rows(self):
        w=self.window
        self.seed_large_history()
        w.filter.setText('ffff')
        w.history_tasks.advance()
        self.assertTrue(w.history_tasks.running('view'))
        self.assertEqual(len(w.packet_indices),2105)
        w.filter.setText('00b5')
        self.finish_history_update()
        self.assertEqual(len(w.packet_indices),2105)
        w.filter.setText('ffff')
        w.history_tasks.advance()
        w.history_cancel.click()
        self.assertTrue(w.history_view_stale)
        self.assertFalse(w.display_save.isEnabled())
        before=list(w.packet_indices)
        w.add_packet(timed_packet(0xb5,bytes(4),timestamp=5000))
        self.assertEqual(w.packet_indices,before)
        w.history_refresh.click()
        self.finish_history_update()
        self.assertEqual(w.packet_indices,[])
        self.assertEqual(w.display_log.toPlainText(),'')
        self.assertTrue(w.display_save.isEnabled())
        w.show_entity_source(2105)
        self.assertFalse(w.history_tasks.busy)
        self.assertEqual(w.selected_packet_index(),2105)

    def test_async_profile_paths_and_emulator_commit_only_after_completed_replay(self):
        w=self.window
        self.seed_large_history()
        previous=w.display_profile_paths['RECV']
        document=json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        next(rule for rule in document['packets'] if '00B5' in rule['ids'])['template']='completed'
        path=Path(self.log_folder.name)/'new-display.json'
        path.write_text(json.dumps(document),encoding='utf-8')
        w.display_path.setText(str(path))
        w.reload_display()
        self.assertEqual(w.display_profile_paths['RECV'],previous)
        w.display_direction.setCurrentText('SEND')
        w.history_cancel.click()
        w.display_direction.setCurrentText('RECV')
        self.assertEqual(w.display_profile_paths['RECV'],previous)
        w.reload_display()
        self.finish_history_update()
        self.assertEqual(w.display_profile_paths['RECV'],str(path))
        self.assertEqual(set(row.text for row in w.display_results),{'completed'})
        w.emulator.setCurrentIndex(1)
        self.assertTrue(w.history_tasks.busy)
        w.history_cancel.click()
        self.assertEqual(w.emulator.currentIndex(),0)
        self.assertEqual(w.display_profile_paths['RECV'],str(path))
        w.emulator.setCurrentIndex(1)
        self.finish_history_update()
        self.assertEqual(w.emulator.currentIndex(),1)
        self.assertEqual(Path(w.display_profile_paths['RECV']).parent.name,'rathena')

    def test_async_reformat_failure_and_close_leave_committed_profile_unchanged(self):
        w=self.window
        self.seed_large_history()
        previous=w.presenter
        previous_results=w.display_results
        with patch('gui.main_window.ReceiveDisplay.decode',side_effect=ValueError('private-payload')):
            w.reformat_display()
            w.history_tasks.advance()
        self.assertFalse(w.history_tasks.busy)
        self.assertIs(w.presenter,previous)
        self.assertIs(w.display_results,previous_results)
        self.assertIn('表示更新に失敗',w.statusBar().currentMessage())
        self.assertNotIn('private-payload',w.statusBar().currentMessage())
        w.reformat_display()
        w.close()
        self.assertFalse(w.history_tasks.busy)
        self.assertFalse(w.history_tasks.timer.isActive())

    def test_background_save_freezes_prefix_filter_and_old_results_before_dialog(self):
        from parser.display import DisplayResult
        from parser.ignorepacket import IgnorePacket
        w=self.window
        self.seed_large_history()
        target=Path(self.log_folder.name)/'snapshot.txt'
        def choose(*args):
            w.filter.setText('ffff')
            w.ignorepacket=IgnorePacket(ids=frozenset({0xb5}))
            w.display_results=[DisplayResult('test','replacement','decoded') for _ in w.events]
            w.add_packet(timed_packet(0xb5,bytes(4),timestamp=9999))
            return str(target),''
        with patch('gui.main_window.QFileDialog.getSaveFileName',side_effect=choose):w.save_display()
        self.assertIsNotNone(w.display_export)
        self.wait_display_export()
        self.assertEqual(target.read_text(encoding='utf-8'),'\n'.join(['old']*2105))
        self.assertEqual(len(w.events),2106)
        self.assertIn('保存しました',w.statusBar().currentMessage())

    def test_background_save_cancel_and_close_wait_for_worker_without_touching_destination(self):
        from threading import Event
        from storage.observation_export import save_observation_chunks
        import sqlite3
        w=self.window
        self.seed_large_history()
        target=Path(self.log_folder.name)/'cancelled.txt'
        target.write_bytes(b'original')
        for close in (False,True):
            entered=Event();release=Event()
            def paused(*args,**kwargs):
                entered.set()
                if not release.wait(30):raise RuntimeError('worker gate timeout')
                return save_observation_chunks(*args,**kwargs)
            with self.subTest(close=close),patch('gui.observation_save.save_observation_chunks',side_effect=paused), \
                    patch('gui.main_window.QFileDialog.getSaveFileName',return_value=(str(target),'')):
                try:
                    w.save_display()
                    self.assertTrue(entered.wait(10))
                    self.assertFalse(w.display_save.isEnabled())
                    self.app.processEvents()
                    if close:
                        w.close()
                        self.assertIsNotNone(w.display_export)
                        self.assertEqual(w.db.db.execute('SELECT 1').fetchone()[0],1)
                    else:w.display_save_cancel.click()
                finally:
                    release.set()
                    self.wait_display_export()
            self.assertEqual(target.read_bytes(),b'original')
            self.assertFalse(list(Path(self.log_folder.name).glob('*.tmp')))
        with self.assertRaises(sqlite3.ProgrammingError):w.db.db.execute('SELECT 1')

    def test_background_save_error_is_generic_and_preserves_existing_file(self):
        w=self.window
        self.seed_large_history()
        target=Path(self.log_folder.name)/'failure.txt'
        target.write_bytes(b'original')
        with patch('gui.main_window.QFileDialog.getSaveFileName',return_value=(str(target),'')), \
                patch('gui.observation_save.save_observation_chunks',side_effect=OSError('private-payload')), \
                patch('gui.main_window.QMessageBox.critical') as warning:
            w.save_display()
            self.wait_display_export()
            warning.assert_called_once()
            self.assertNotIn('private-payload',str(warning.call_args))
        self.assertEqual(target.read_bytes(),b'original')
        self.assertTrue(w.display_save.isEnabled())

    def test_packet_pages_preserve_source_indices_filter_and_old_page_during_capture(self):
        from events import PacketEvent
        from PySide6.QtCore import Qt
        w=self.window
        for index in range(1005):
            pid=127 if index%2==0 else 128
            w.add_packet(PacketEvent(index,'RECV',pid,pid.to_bytes(2,'little'),'TEST','flow'))
        self.assertEqual(w.table.rowCount(),5)
        self.assertEqual(w.table.item(0,0).data(Qt.UserRole),1000)
        w.packet_pager.previous.click()
        self.assertEqual(w.table.rowCount(),1000)
        w.table.selectRow(3)
        w.add_packet(PacketEvent(1005,'RECV',128,b'\x80\0','TEST','flow'))
        self.assertEqual(w.selected_packet_index(),3)
        w.show_entity_source(1004)
        self.assertEqual(w.selected_packet_index(),1004)
        self.assertIn('0x007F',w.hex.toPlainText())
        w.reformat_display()
        self.assertEqual(w.selected_packet_index(),1004)
        self.assertEqual(len(w.events),1006)
        w.filter.setText('0080')
        self.assertEqual(w.table.rowCount(),503)
        w.table.selectRow(2)
        self.assertEqual(w.selected_packet_index(),5)
        with patch.object(w,'set_ignore_member') as change:
            w.toggle_selected_packet_ignore(True)
        change.assert_called_once_with('ids',128,True)
        self.assertEqual(w.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0],1006)

    def test_memory_eviction_keeps_db_evidence_and_never_drops_unsaved(self):
        from events import PacketEvent
        w=self.window
        w.memory_event_limit=20
        for index in range(25):
            w.add_packet(PacketEvent(index,'RECV',127,b'\x7f\0abcd','TEST','flow'))
        self.assertEqual(w.event_origin,5)
        self.assertEqual(len(w.events),20)
        self.assertEqual(w.packet_db_confirmed,25)
        self.assertEqual(w.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0],25)
        self.assertIn('退避 5',w.counter.text())
        w.show_entity_source(0)
        self.assertIn('退避済み Packet #0',w.hex.toPlainText())
        self.assertIn('0x007F',w.hex.toPlainText())
        w.show_entity_source(24)
        self.assertEqual(w.selected_packet_index(),24)
        w.database_failed=True
        before=w.event_origin
        for index in range(25,30):
            w.add_packet(PacketEvent(index,'RECV',128,b'\x80\0efgh','TEST','flow'))
        self.assertEqual(w.event_origin,before)
        self.assertGreaterEqual(len(w.events),20)

    def test_live_packet_table_stays_paged_under_memory_cap_flood(self):
        from events import PacketEvent
        from gui.view_limits import DISPLAY_LIMIT
        from unittest.mock import patch
        w=self.window
        direction='R'+'E'+'C'+'V'
        w.memory_event_limit=50
        # Full page rebuilds during prefix eviction used to thrash the GUI under floods.
        with patch.object(w,'render_packet_page',wraps=w.render_packet_page) as rebuild:
            peak_rows=0
            for index in range(120):
                w.add_packet(PacketEvent(index,direction,127,b'\x7f\0abcd','TEST','flow'))
                peak_rows=max(peak_rows,w.table.rowCount())
                self.assertLessEqual(w.table.rowCount(),DISPLAY_LIMIT)
            self.assertEqual(w.event_origin,70)
            self.assertEqual(len(w.events),50)
            # After eviction only the retained window is indexed; live page stays that size.
            self.assertEqual(w.table.rowCount(),50)
            self.assertEqual(peak_rows,50)
            # Evict-before-UI keeps a single page stable — no full rebuilds required.
            self.assertEqual(rebuild.call_count,0)

    def test_live_packet_table_avoids_rebuild_thrash_at_page_aligned_cap(self):
        from events import PacketEvent
        from gui.view_limits import DISPLAY_LIMIT
        from unittest.mock import patch
        w=self.window
        direction='R'+'E'+'C'+'V'
        # Cap aligned to DISPLAY_LIMIT used to flip page N↔N+1 every packet after the cap.
        w.memory_event_limit=2*DISPLAY_LIMIT
        with patch.object(w,'render_packet_page',wraps=w.render_packet_page) as rebuild:
            for index in range(2*DISPLAY_LIMIT+150):
                w.add_packet(PacketEvent(index,direction,127,b'\x7f\0abcd','TEST','flow'))
                self.assertLessEqual(w.table.rowCount(),DISPLAY_LIMIT)
            self.assertEqual(len(w.events),2*DISPLAY_LIMIT)
            self.assertEqual(w.table.rowCount(),DISPLAY_LIMIT)
            # One rebuild when first crossing onto the latest full page; post-cap packets
            # must slide rows without rebuilding the whole table each time.
            self.assertLessEqual(rebuild.call_count,3)
            self.assertLess(rebuild.call_count,150)

    def test_bounded_observation_document_saves_full_matching_history(self):
        from unittest.mock import Mock
        from parser.display import DisplayResult
        from events import PacketEvent
        w=self.window
        w.presenter=Mock()
        w.presenter.decode.side_effect=lambda packet,*args:DisplayResult('test','message-'+str(int(packet.timestamp))+'-'+'x'*500,'decoded')
        for index in range(1100):
            w.add_packet(PacketEvent(index,'RECV',127,b'\x7f\0','TEST','flow'))
        # Live append may overshoot briefly between throttled trims (avoids toPlainText thrash).
        self.assertLessEqual(len(w.display_log.toPlainText()),w.DISPLAY_TEXT_LIMIT+8192)
        self.assertNotIn('message-0-',w.display_log.toPlainText())
        self.assertIn('message-1099-',w.display_log.toPlainText())
        w.rebuild_display_log()
        self.assertLessEqual(len(w.display_log.toPlainText()),w.DISPLAY_TEXT_LIMIT)
        target=Path(self.log_folder.name)/'all-observations.txt'
        def choose(*args):
            w.filter.setText('ffff')
            return str(target),''
        with patch('gui.main_window.QFileDialog.getSaveFileName',side_effect=choose):w.save_display()
        self.wait_display_export()
        saved=target.read_text(encoding='utf-8')
        self.assertEqual(len(saved.splitlines()),1100)
        self.assertIn('message-0-',saved)
        self.assertIn('message-1099-',saved)
        self.assertEqual(w.display_log.toPlainText(),'')
        self.assertEqual(len(w.display_results),1100)

    def test_appearance_history_navigates_changes_preserves_selection_and_clears_hidden_entity(self):
        from copy import deepcopy
        from tests.support.world import map_packet,packet
        w=self.window
        w.add_packet(map_packet('test.gat'))
        for kind,aid,panel,first_class,next_class in ((6,42,w.npc_panel,139,844),(5,142,w.mob_panel,1005,1006)):
            w.add_packet(actor_packet(actor_id=aid,actor_type=kind))
            change_index=len(w.events)
            change=packet(0x1b0,struct.pack('<IBI',aid,0,first_class))
            w.add_packet(change);w.add_packet(change)
            w.add_packet(packet(0x229,struct.pack('<IHHIB',aid,0,0,2,0)))
            panel.set_records(w.world.records('NPC' if kind==6 else 'MOB'))
            row=next(i for i,e in enumerate(panel.model.rows) if e.actor_id==aid)
            panel.table.setCurrentIndex(panel.model.index(row,0))
            history=panel.appearance_history
            self.assertEqual(history.table.rowCount(),2)
            history.table.selectRow(0)
            self.assertIn('class:',history.table.item(0,2).text())
            self.assertEqual(history.selected()['packet_index'],change_index)
            history.source_button.click()
            self.assertEqual(w.table.currentRow(),change_index)
            w.add_packet(packet(0x1b0,struct.pack('<IBI',aid,0,next_class)))
            w.refresh_entity_views()
            self.assertEqual(history.table.rowCount(),3)
            self.assertEqual(history.selected()['packet_index'],change_index)
            before=deepcopy(w.world.snapshot())
            history.table.selectRow(1);history.source_button.click()
            self.assertEqual(w.world.snapshot(),before)
            w.add_packet(packet(0x80,struct.pack('<IB',aid,0)))
            w.refresh_entity_views()
            panel.active_only.setChecked(True)
            self.assertEqual(history.table.rowCount(),0)
            self.assertFalse(history.source_button.isEnabled())
            self.assertEqual(history.detail.toPlainText(),'')
            with patch.object(history,'on_source') as source:history.jump()
            source.assert_not_called()

    def test_appearance_history_bounds_and_reappearance_warning_keep_original_initial_class(self):
        from copy import deepcopy
        from tests.support.world import packet
        w=self.window
        w.add_packet(actor_packet(name='Guide'))
        for cls in range(139,179):
            w.add_packet(packet(0x1b0,struct.pack('<IBI',42,0,cls)))
        panel=w.npc_panel
        panel.set_records(w.world.records('NPC'))
        panel.table.setCurrentIndex(panel.model.index(0,0))
        history=panel.appearance_history
        self.assertEqual(history.table.rowCount(),32)
        self.assertEqual(history.rows[0]['packet_index'],9)
        self.assertEqual(history.rows[-1]['packet_index'],40)
        self.assertFalse(history.select_key((0,1)))
        w.add_packet(packet(0x80,struct.pack('<IB',42,0)))
        reappeared=actor_packet(name='Guide')
        w.add_packet(reappeared)
        panel.set_records(w.world.records('NPC'))
        row=next(i for i,e in enumerate(panel.model.rows) if e.active)
        panel.table.setCurrentIndex(panel.model.index(row,0))
        self.assertEqual(history.table.rowCount(),1)
        self.assertIn('変更時点は未観測',history.table.item(0,3).text())
        self.assertIn('class: 178 → 45',history.table.item(0,2).text())
        self.assertEqual(panel.model.rows[row].initial_display['class_id'],45)
        before=deepcopy(w.world.snapshot())
        history.source_button.click()
        self.assertEqual(w.table.currentRow(),42)
        self.assertEqual(w.world.snapshot(),before)

    def test_entity_panels_sort_by_server_actor_and_keep_selection(self):
        w=self.window
        for kind,panel in ((6,w.npc_panel),(5,w.mob_panel)):
            for ip,port,aid in (('10.0.0.10',5121,1),('10.0.0.2',6121,1),
                                ('10.0.0.2',5121,10),('10.0.0.2',5121,2)):
                connection=str((ip,port,'192.0.2.1',50000))
                w.add_packet(actor_packet(actor_id=aid,actor_type=kind,connection=connection))
            panel.set_records(reversed(w.world.records('NPC' if kind==6 else 'MOB')))
            self.assertEqual([e.actor_id for e in panel.model.rows],[2,10,1,1])
            panel.table.setCurrentIndex(panel.model.index(1,0))
            selected=panel.model.rows[1].key
            panel.set_records(reversed(panel.records))
            self.assertEqual(panel.model.rows[panel.table.currentIndex().row()].key,selected)

    def test_actor_first_log_and_change_only_keep_raw_packets_and_initial_display(self):
        from dataclasses import replace
        from reconstruction.npc_bundle import build_npc_bundle
        from tests.support.world import map_packet
        w=self.window
        w.add_packet(map_packet('test.gat'))
        event=actor_packet(name='Guide')
        raw=bytearray(event.raw)
        struct.pack_into('<H',raw,23,4001)
        raw[62]=1
        struct.pack_into('<H',raw,25,3)
        event=replace(event,raw=bytes(raw))
        w.add_packet(event);w.add_packet(event)
        raw[25:27]=struct.pack('<H',4)
        w.add_packet(replace(event,raw=bytes(raw)))
        text=w.display_log.toPlainText()
        self.assertEqual(text.count('初回観測'),1)
        self.assertIn('髪型: 3 → 4',text)
        self.assertEqual(len(w.events),4)
        w.npc_panel.set_records(w.world.records('NPC'))
        w.npc_panel.table.setCurrentIndex(w.npc_panel.model.index(0,0))
        detail=w.npc_panel.detail.toPlainText()
        self.assertIn('外見class: 初回 4001 / 現在 4001',detail)
        self.assertIn('配置class: 844',detail)
        self.assertIn('髪型: 3 → 4',detail)
        self.assertIn('性別: 1 → 1',detail)
        self.assertIn('髪型: 3 → 4',w.npc_panel.appearance_history.table.item(0,2).text())
        report=build_npc_bundle(w.world.snapshot('NPC')['entities'],[])
        self.assertIn('\tscript\tGuide\t844,{/*',report['auriga'])
        self.assertIn('setnpcdisplay "Guide",4001,1,3,0,0,0,0,0,0,0;',report['auriga'])

    def test_unassigned_music_visible_with_npc_exclusion_and_hidden_by_packet_id_only(self):
        from parser.ignorepacket import IgnorePacket
        from tests.support.dialogue import music_event
        w = self.window
        w.ignorepacket = IgnorePacket(npc_actors=frozenset({42}), npc_names=frozenset({'案内人'}))
        w.add_packet(music_event())
        self.assertIn('theme.mp3', w.display_log.toPlainText())
        self.assertIsNone(w.dialogues.presentation_observations[-1]['actor_id'])
        w.ignorepacket = IgnorePacket(ids=frozenset({0x7fe}))
        w.rebuild_display_log()
        self.assertEqual(w.display_log.toPlainText(), '')
        self.assertEqual(len(w.dialogues.presentation_observations), 1)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 1)

    def test_reload_ignore_settings_updates_controls_without_saving_and_retains_on_error(self):
        from parser.ignorepacket import IgnorePacket
        from tests.support.dialogue import packet
        w = self.window
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        w.table.setCurrentCell(0, 0)
        settings = IgnorePacket(ids=frozenset({0xb4}), mob_combat=True)
        with patch.object(IgnorePacket, 'load', return_value=settings), patch.object(IgnorePacket, 'save') as save:
            w.reload_ignorepacket()
            self.assertEqual(w.display_log.toPlainText(), '')
            self.assertTrue(w.ignore_mob.isChecked())
            self.assertTrue(w.ignore_packet_selection.isChecked())
            save.assert_not_called()
        with patch.object(IgnorePacket, 'load', side_effect=ValueError('invalid')):
            w.reload_ignorepacket()
            self.assertEqual(w.ignorepacket, settings)
            self.assertEqual(w.display_log.toPlainText(), '')
            self.assertIn('現在の設定を保持', w.statusBar().currentMessage())

    def test_selected_packet_and_npc_exclusions_are_reversible_and_selection_safe(self):
        from parser.ignorepacket import IgnorePacket
        from tests.support.dialogue import packet
        w = self.window
        self.assertFalse(w.ignore_packet_selection.isEnabled())
        self.assertFalse(w.ignore_npc_selection.isEnabled())
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'hello\0'))
        w.add_packet(packet(0xb6, struct.pack('<I', 42)))
        with patch.object(IgnorePacket, 'save') as save:
            w.table.setCurrentCell(0, 0)
            w.ignore_packet_selection.click()
            self.assertIn(0xb4, w.ignorepacket.ids)
            self.assertNotIn('hello', w.display_log.toPlainText())
            w.table.setCurrentCell(1, 0)
            self.assertFalse(w.ignore_packet_selection.isChecked())
            self.assertNotIn(0xb6, w.ignorepacket.ids)
            w.table.setCurrentCell(0, 0)
            self.assertTrue(w.ignore_packet_selection.isChecked())
            w.ignore_packet_selection.click()
            self.assertIn('hello', w.display_log.toPlainText())
            self.assertEqual(save.call_count, 2)
            w.add_packet(actor_packet(actor_id=43, name='案内人'))
            w.add_packet(actor_packet(actor_id=44, name='別のNPC'))
            w.npc_panel.set_records(w.world.records('NPC'))
            table, model = w.npc_panel.table, w.npc_panel.model
            row = next(i for i, entity in enumerate(model.rows) if entity.actor_id == 43)
            table.setCurrentIndex(model.index(row, 0))
            w.ignore_npc_selection.click()
            self.assertIn(43, w.ignorepacket.npc_actors)
            w.add_packet(packet(0xc0, struct.pack('<IB', 43, 3), connection='flow-a', flow=''))
            hidden = w.display_log.toPlainText()
            row = next(i for i, entity in enumerate(model.rows) if entity.actor_id == 44)
            table.setCurrentIndex(model.index(row, 0))
            self.assertFalse(w.ignore_npc_selection.isChecked())
            self.assertNotIn(44, w.ignorepacket.npc_actors)
            row = next(i for i, entity in enumerate(model.rows) if entity.actor_id == 43)
            table.setCurrentIndex(model.index(row, 0))
            self.assertTrue(w.ignore_npc_selection.isChecked())
            w.ignore_npc_selection.click()
            self.assertNotEqual(w.display_log.toPlainText(), hidden)
            self.assertNotIn(43, w.ignorepacket.npc_actors)
            self.assertEqual(save.call_count, 4)
            w.npc_panel.set_records([])
            self.assertFalse(w.ignore_npc_selection.isEnabled())

    def test_ignorepacket_rebuild_preserves_analysis_and_raw_packets(self):
        from parser.ignorepacket import IgnorePacket
        from tests.support.dialogue import packet
        w = self.window
        for record in (packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                       packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                       packet(0xb6, struct.pack('<I', 42))):
            w.add_packet(record)
        original = w.display_log.toPlainText()
        w.ignorepacket = IgnorePacket(ids=frozenset({0x90, 0xb4}))
        w.rebuild_display_log()
        self.assertNotIn('hello', w.display_log.toPlainText())
        self.assertIn('close;', w.display_log.toPlainText())
        w.dialogue_panel.refresh()
        self.assertIn('mes "hello";', w.dialogue_panel.code.toPlainText())
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 3)
        self.assertEqual(w.table.rowCount(), 3)
        w.reformat_display()
        self.assertNotIn('hello', w.display_log.toPlainText())
        w.ignorepacket = IgnorePacket()
        w.rebuild_display_log()
        self.assertEqual(w.display_log.toPlainText(), original)

    def test_ignorepacket_skip_save_keeps_analysis_without_sqlite_row(self):
        from parser.ignorepacket import IgnorePacket
        from tests.support.dialogue import packet
        w = self.window
        w.ignorepacket = IgnorePacket(skip_save=frozenset({0xb4}))
        before = self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0]
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'skip\0'))
        w.add_packet(packet(0xb6, struct.pack('<I', 42)))
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], before + 1)
        self.assertEqual(w.packet_rowids[-2], 0)
        self.assertIn('mes "skip";', w.display_log.toPlainText())
        self.assertIn('close;', w.display_log.toPlainText())
        w.dialogue_panel.refresh()
        self.assertIn('mes "skip";', w.dialogue_panel.code.toPlainText())

    def test_mob_checkbox_and_npc_list_hide_live_and_existing_lines(self):
        from parser.ignorepacket import IgnorePacket
        from gui.ignorepacket import IgnorePacketDialog
        from tests.support.skills import mob, damage
        from tests.support.dialogue import packet
        w = self.window
        w.add_packet(mob())
        w.add_packet(damage())
        original = w.display_log.toPlainText()
        with patch.object(IgnorePacket, 'save') as save:
            w.ignore_mob.setChecked(True)
            self.assertTrue(save.called)
            hidden = w.display_log.toPlainText()
            self.assertNotEqual(hidden, original)
            w.add_packet(damage(timestamp=2))
            self.assertEqual(w.display_log.toPlainText(), hidden)
            w.ignore_mob.setChecked(False)
        self.assertNotEqual(w.display_log.toPlainText(), hidden)
        w.add_packet(actor_packet(actor_id=43, name='案内人'))
        dialog = IgnorePacketDialog(IgnorePacket(), w)
        dialog.ids.setPlainText('007e, 0085')
        dialog.npcs.setPlainText('id:0x2b\nname:案内人')
        w.ignorepacket = dialog.settings()
        w.rebuild_display_log()
        before = w.display_log.toPlainText()
        w.add_packet(packet(0xc0, struct.pack('<IB', 43, 3), connection='flow-a', flow=''))
        self.assertEqual(w.display_log.toPlainText(), before)
        self.assertEqual(w.observation_tags[-1]['npc_name'], '案内人')
        w.add_packet(packet(0x1b0, struct.pack('<IBI', 43, 1, 1005), connection='flow-a', flow=''))
        self.assertEqual(w.display_log.toPlainText(), before)
        self.assertEqual(w.dialogues.presentation_observations[-1]['kind'], 'classchange')
        w.add_packet(packet(0x9d1, struct.pack('<III', 43, 0xabcdef, 3), connection='flow-a', flow=''))
        self.assertEqual(w.display_log.toPlainText(), before)
        self.assertEqual(w.dialogues.presentation_observations[-1]['kind'], 'progressbar')
        w.add_packet(packet(0x144, struct.pack('<IIIIBI', 43, 1, 100, 200, 7, 0xff123456),
                            connection='flow-a', flow=''))
        self.assertEqual(w.display_log.toPlainText(), before)
        self.assertEqual(w.dialogues.presentation_observations[-1]['kind'], 'viewpoint')
        from tests.support.dialogue import overhead_event
        from dataclasses import replace
        w.add_packet(replace(overhead_event(actor=43), connection='flow-a', flow_id=''))
        self.assertEqual(w.display_log.toPlainText(), before)
        self.assertEqual(w.dialogues.presentation_observations[-1]['kind'], 'overhead')
        w.add_packet(packet(0x2f0, struct.pack('<II', 0xabcdef, 3), connection='flow-a', flow=''))
        self.assertNotEqual(w.display_log.toPlainText(), before)
        self.assertFalse(w.dialogues.presentation_observations[-1]['target_observed'])
        dialog.npcs.setPlainText('id:-1')
        with self.assertRaises(ValueError):
            dialog.settings()
        dialog.close()

    def test_close_reply_continuation_updates_code_and_keeps_source_rows(self):
        from tests.support.dialogue import packet
        w = self.window
        records = [packet(0x90, struct.pack('<IB', 42, 1), 'SEND'),
                   packet(0xb4, struct.pack('<I', 42) + b'hello\0'),
                   packet(0xb6, struct.pack('<I', 42))]
        for record in records:
            w.add_packet(record)
        panel = w.dialogue_panel
        panel.refresh()
        self.assertIn('close;', panel.code.toPlainText())
        self.assertNotIn('close2;', panel.code.toPlainText())
        w.add_packet(packet(0x146, struct.pack('<I', 42), 'SEND'))
        w.add_packet(packet(0xb4, struct.pack('<I', 42) + b'continued\0'))
        w.add_packet(packet(0x1b3, b'portrait.bmp'.ljust(64, b'\0') + b'\x02'))
        w.add_packet(packet(0x91, b'test.gat'.ljust(16, b'\0') + struct.pack('<HH', 10, 20)))
        w.add_packet(packet(0x1b3, bytes(64) + b'\xff'))
        panel.refresh()
        code = panel.code.toPlainText()
        self.assertIn('close2;', code)
        self.assertIn('warp "test.gat",10,20;', code)
        self.assertIn('mes "continued";', code)
        self.assertLess(code.index('warp '), code.rindex('cutin '))
        self.assertTrue(code.rstrip().endswith('end;'))
        self.assertIn('after_close_reply', panel.evidence.toPlainText())
        self.assertEqual(panel.selection.count(), 1)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 8)

    def test_overlay_editor_saves_index_and_reloads_detail(self):
        w = self.window
        packet = variable(0xB4, struct.pack('<I', 42) + b'hello\0')
        w.add_packet(packet)
        w.table.selectRow(0)
        self.assertTrue(w.overlay_edit.isEnabled())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'overlay.json'
            from gui.overlay_editor import OverlayEditorDialog
            from parser.packet_overlay import save_overlay, upsert_overlay_packet
            dialog = OverlayEditorDialog(
                0xb4, len(packet.raw),
                display_rule=w.presenter.profile.rules[0xb4],
                overlay_path=str(path), parent=w)
            for row in range(dialog.table.rowCount()):
                item = dialog.table.item(row, 0)
                if item and item.text() == 'actor_id':
                    dialog.table.cellWidget(row, 4).setCurrentText('actor_id')
            entry = dialog.build_entry()
            self.assertEqual(entry['fields']['actor_id']['index'], 'actor_id')
            save_overlay(path, upsert_overlay_packet(None, entry))
            w.overlay_path.setText(str(path))
            w.reload_display()
            w.table.selectRow(0)
            w.show_selected()
            self.assertIn('actor_id: 42（未観測）', w.hex.toPlainText())
            self.assertTrue(path.is_file())
            dialog.close()

    def test_same_id_diff_and_overlay_export(self):
        w = self.window
        first = variable(0xB4, struct.pack('<I', 42) + b'hello\0')
        second = variable(0xB4, struct.pack('<I', 99) + b'hello\0')
        w.add_packet(first)
        w.add_packet(second)
        w.table.selectRow(0)
        w.table.selectRow(1)  # ExtendedSelection keeps both when using Ctrl; force multi-select
        from PySide6.QtCore import QItemSelectionModel
        model = w.table.selectionModel()
        model.select(w.table.model().index(0, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        model.select(w.table.model().index(1, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.assertTrue(w.overlay_diff.isEnabled())
        w.diff_same_id_instances()
        self.assertIn('同一ID差分: 0x00B4', w.hex.toPlainText())
        self.assertIn('actor_id', w.hex.toPlainText())
        with tempfile.TemporaryDirectory() as folder:
            example = Path('config/packet_overlay.example.json')
            w.overlay_path.setText(str(example.resolve()))
            w.sync_ignore_selection()
            self.assertTrue(w.overlay_export.isEnabled())
            with patch('gui.main_window.QFileDialog.getExistingDirectory', return_value=folder), \
                    patch('gui.main_window.QMessageBox.information'):
                w.export_confirmed_overlay()
            self.assertTrue((Path(folder) / 'PacketLength.overlay-export.txt').is_file())
            self.assertTrue((Path(folder) / 'display.overlay-export.json').is_file())
            self.assertIn('F001', (Path(folder) / 'PacketLength.overlay-export.txt').read_text(encoding='utf-8'))

    def test_display_filter_detail_save_and_raw_storage(self):
        w = self.window
        packet = variable(0xB4, struct.pack('<I', 42) + b'hello\0')
        w.add_packet(packet)
        w.add_packet(event(0xB5, bytes(4)))
        w.add_packet(event(0xFFFF))
        w.add_packet(event(0xB5, bytes(4), direction='SEND'))
        self.assertEqual(w.table.item(0, 5).text(), 'mes "hello";')
        self.assertIn('next;', w.display_log.toPlainText())
        w.table.selectRow(0)
        w.show_selected()
        self.assertIn('actor_id: 42', w.hex.toPlainText())
        self.assertIn('B4 00', w.hex.toPlainText())
        w.display_unmapped.setChecked(False)
        self.assertNotIn('@packet', w.display_log.toPlainText())
        w.filter.setText('00b4')
        self.assertEqual(w.display_log.toPlainText(), 'mes "hello";')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'receive.txt'
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                w.save_display()
            self.assertEqual(path.read_text(encoding='utf-8'), 'mes "hello";')
        self.assertEqual(self.db.db.execute('SELECT raw FROM packets ORDER BY id LIMIT 1').fetchone()[0], packet.raw)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 4)

    def test_reload_replays_history_and_retains_last_good_profile(self):
        w = self.window
        w.add_packet(event(0xB5, bytes(4)))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'display.json'
            document = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
            next(rule for rule in document['packets'] if '00B5' in rule['ids'])['template'] = '次へ'
            path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            w.display_path.setText(str(path))
            w.reload_display()
            self.assertEqual(w.display_log.toPlainText(), '次へ')
            path.write_text('{broken', encoding='utf-8')
            w.reload_display()
            self.assertIn('previous profile retained', w.statusBar().currentMessage())
            w.add_packet(event(0xB5, bytes(4)))
            self.assertEqual(w.display_log.toPlainText(), '次へ\n次へ')

    def test_timestamps_and_session_replay_isolation(self):
        w = self.window
        w.add_packet(event(0x1B3, bytes(64) + b'\x01'))
        w.add_packet(event(0xB6, bytes(4)))
        w.capture_session += 1
        w.presenter.reset()
        w.add_packet(event(0xB6, bytes(4)))
        w.reload_display()
        self.assertEqual([r.text for r in w.display_results][-2:], ['close;', 'close;'])
        w.display_timestamps.setChecked(True)
        self.assertTrue(w.display_results[-1].text.startswith('/* '))
        self.assertTrue(w.display_results[-1].text.endswith('close;'))

    def test_send_display_reload_and_receive_history_coexist(self):
        w = self.window
        w.add_packet(event(0xB5, bytes(4)))
        w.add_packet(event(0x89, struct.pack('<IB', 42, 7), direction='SEND'))
        self.assertEqual(w.display_results[0].text, 'next;')
        self.assertEqual(w.display_results[1].text, 'SEND actor_action target=42, type=7')
        self.assertEqual(self.db.db.execute('SELECT direction FROM packets ORDER BY id').fetchall(),
                         [('RECV',), ('SEND',)])
        w.display_direction.setCurrentText('SEND')
        path = Path(self.log_folder.name) / 'send.json'
        document = json.loads(Path(w.display_path.text()).read_text(encoding='utf-8'))
        rule = next(rule for rule in document['packets'] if '0089' in rule['ids'])
        rule['template'] = '送信 対象={target_id} 動作={action}'
        path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        w.display_path.setText(str(path))
        w.reload_display()
        self.assertEqual(w.display_results[0].text, 'next;')
        self.assertEqual(w.display_results[1].text, '送信 対象=42 動作=7')
        w.display_timestamps.setChecked(True)
        self.assertTrue(w.display_results[1].text.endswith('送信 対象=42 動作=7'))
        w.display_direction.setCurrentText('RECV')
        self.assertEqual(w.display_path.text(), str(DEFAULT_PROFILE))

    def test_display_map_hint_and_first_appearance_survive_reformat(self):
        from tests.support.player import packet
        from dataclasses import replace
        w = self.window
        w.add_packet(packet(0x71, struct.pack('<I', 123) + b'test.gat'.ljust(16, b'\0') + bytes(6), flow='char'))
        w.add_packet(packet(0x436, struct.pack('<II', 42, 123) + bytes(13), direction='SEND'))
        actor = replace(actor_packet(), flow_id='game')
        w.add_packet(actor)
        w.add_packet(actor)
        self.assertIn('map="test.gat"', w.display_results[2].text)
        self.assertIn('初回観測', w.display_results[2].text)
        self.assertNotIn('初回観測', w.display_results[3].text)
        before = [result.text for result in w.display_results]
        w.reload_display()
        self.assertEqual([result.text for result in w.display_results], before)

    def test_emulator_preset_changes_receive_display_only(self):
        w = self.window
        w.add_packet(event(0xB5, bytes(4)))
        w.add_packet(event(0x89, struct.pack('<IB', 42, 7), direction='SEND'))
        original_send = w.display_results[1].text
        w.emulator.setCurrentIndex(1)
        self.assertEqual(Path(w.display_path.text()).parent.name, 'rathena')
        self.assertIn(0xB5, w.presenter.profile.rules)
        self.assertIn(0xB72, w.presenter.profile.rules)
        self.assertEqual(w.display_results[0].text, 'next;')
        self.assertEqual(w.display_results[1].text, original_send)
        self.assertIn('rAthena', w.mode_summary.text())
        w.emulator.setCurrentIndex(0)
        self.assertEqual(w.display_path.text(), str(DEFAULT_PROFILE))
        self.assertIn(0x99D, w.presenter.profile.rules)

    def test_broken_emulator_preset_retains_previous_profile(self):
        w = self.window
        previous = w.presenter
        with patch('gui.main_window.DisplayProfile.load', side_effect=ValueError('invalid profile')):
            w.emulator.setCurrentIndex(1)
        self.assertEqual(w.emulator.currentIndex(), 0)
        self.assertIs(w.presenter, previous)
        self.assertIn('invalid profile', w.capture_log.toPlainText())

    def test_packet_filter_is_visible_and_clearable_in_observation_view(self):
        w = self.window
        w.add_packet(variable(0xB4, struct.pack('<I', 42) + b'hello\0'))
        w.add_packet(event(0xB5, bytes(4)))
        w.filter.setText('00B4')
        self.assertFalse(w.filter_notice.isHidden())
        self.assertIn('00B4', w.filter_notice_label.text())
        self.assertNotIn('next;', w.display_log.toPlainText())
        w.clear_filter.click()
        self.assertTrue(w.filter_notice.isHidden())
        self.assertIn('next;', w.display_log.toPlainText())

    def test_user_settings_profile_persists_across_restart(self):
        from gui.main_window import MainWindow
        from storage.database import PacketDatabase
        from storage.user_settings import load
        from reconstruction.emulator_profiles import set_target
        w = self.window
        w.capture_send.setChecked(False)
        w.children.setChecked(True)
        w.display_timestamps.setChecked(True)
        w.display_unmapped.setChecked(True)
        w.record_stream.setChecked(True)
        w.offline_max_packets.setValue(45000)
        w.offline_max_packet_mib.setValue(64)
        w.pipe_name.setText('gpa-persist-test')
        w.dialogue_panel.merge_checkbox.setChecked(True)
        w.persist_user_settings()
        saved = load(self.settings_path)
        self.assertFalse(saved['capture_send'])
        self.assertTrue(saved['include_children'])
        self.assertTrue(saved['display_timestamps'])
        self.assertTrue(saved['display_unmapped'])
        self.assertTrue(saved['record_stream'])
        self.assertEqual(saved['offline_max_packets'], 45000)
        self.assertEqual(saved['offline_max_packet_mib'], 64)
        self.assertEqual(saved['pipe_name'], 'gpa-persist-test')
        self.assertTrue(saved['merge_npc_paths'])
        db = PacketDatabase(':memory:')
        with patch('gui.main_window.PacketDatabase', return_value=db), \
             patch('gui.main_window.list_processes', return_value=[]):
            restarted = MainWindow()
        try:
            self.assertFalse(restarted.capture_send.isChecked())
            self.assertTrue(restarted.children.isChecked())
            self.assertTrue(restarted.display_timestamps.isChecked())
            self.assertTrue(restarted.display_unmapped.isChecked())
            self.assertTrue(restarted.record_stream.isChecked())
            self.assertEqual(restarted.offline_max_packets.value(), 45000)
            self.assertEqual(restarted.offline_max_packet_mib.value(), 64)
            self.assertEqual(restarted.pipe_name.text(), 'gpa-persist-test')
            self.assertTrue(restarted.dialogue_panel.merge_checkbox.isChecked())
            self.assertTrue(restarted.export_merge_action.isChecked())
        finally:
            set_target('auriga')
            restarted.close()
            from PySide6.QtCore import QElapsedTimer
            from PySide6.QtTest import QTest
            elapsed = QElapsedTimer(); elapsed.start()
            while not restarted.workspace_closed and elapsed.elapsed() < 60000:
                self.app.processEvents(); QTest.qWait(1)
