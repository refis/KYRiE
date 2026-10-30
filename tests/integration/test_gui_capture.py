import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from tests.support.world import actor_packet



from tests.support.qt import WindowTestCase


class CaptureGuiTests(WindowTestCase):
    def test_close_seals_admission_and_drains_queued_packets_before_database_close(self):
        from contextlib import closing
        from threading import Thread
        import sqlite3
        from storage.database import PacketDatabase
        from events import PacketEvent
        w=self.window
        path=Path(self.log_folder.name)/'closing.sqlite3'
        w.db.close();w.db=PacketDatabase(path)
        with patch('gui.main_window.load_lengths',return_value={127:6}),patch('gui.main_window.Receiver'):
            w.start()
            log=w.session_log.path
            events=[PacketEvent(index,'RECV',127,b'\x7f\0abcd','TEST','flow') for index in range(4)]
            producer=Thread(target=lambda:[w.bridge.publish(1,event) for event in events])
            producer.start();producer.join()
            w.close()
            self.assertFalse(w.workspace_closed)
            self.assertFalse(w.session_log.closed)
            self.assertEqual(w.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0],0)
            self.assertFalse(w.bridge.publish(1,events[0]))
            self.wait_window_closed()
            self.assertEqual(w.events,events)
            self.assertFalse(w.database_failed)
            self.assertEqual(w.packet_progress()['awaiting_gui'],0)
            self.assertEqual(w.packet_progress()['pending_bytes'],0)
            self.assertEqual(w.packet_progress()['shutdown_rejected'],1)
            self.assertFalse(w.packet_progress()['overflowed'])
            with closing(sqlite3.connect(path)) as reader:
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM packets').fetchone()[0],4)
            rows=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            summary=next(row for row in rows if row['kind']=='packet_delivery_shutdown')
            self.assertEqual(summary['counts_at_close']['db_confirmed'],4)
            self.assertEqual(rows[-1]['kind'],'session_end')
            w.add_packet(events[0])
            self.assertEqual(w.events,events)

    def test_frozen_reports_survive_capture_stop_and_db_failure_without_mixing_late_packets(self):
        from threading import Event,Thread
        from reconstruction.report_snapshot import freeze_npc_report,freeze_mob_report
        from tests.support.world import map_packet
        from events import PacketEvent
        import sqlite3
        w=self.window
        for fail in (False,True):
            with self.subTest(db_failure=fail),patch('gui.main_window.load_lengths',return_value={127:6}), \
                    patch('gui.main_window.Receiver'):
                w.start()
                w.bridge.publish(w.capture_session,map_packet())
                w.bridge.publish(w.capture_session,actor_packet())
                prepared=(freeze_npc_report(w.world.snapshot('NPC')['entities'],w.dialogues.sessions,
                    w.world_sources,merge=True,shops=w.shops.records) if fail else
                    freeze_mob_report(w.skills,w.world_sources,w.mob_skills_panel.names))
                original=type(prepared).build
                expected=prepared.build()
                target=Path(self.log_folder.name)/('concurrent-'+str(fail)+'.json')
                entered=Event();release=Event()
                def build(snapshot):
                    entered.set()
                    if not release.wait(3):raise RuntimeError('generation gate timeout')
                    return original(snapshot)
                with patch.object(type(prepared),'build',new=build):
                    try:
                        w.save_prepared_report(target,prepared,[],label='NPC')
                        self.assertTrue(entered.wait(1))
                        count=len(w.events)
                        producer=Thread(target=lambda:[w.bridge.publish(w.capture_session,
                            PacketEvent(index+10,'RECV',127,b'\x7f\0abcd','TEST','flow')) for index in range(3)])
                        producer.start();producer.join()
                        if fail:
                            with patch.object(w.db,'add',side_effect=sqlite3.OperationalError('private-payload')) as add:
                                self.app.processEvents()
                            add.assert_called_once()
                            self.assertEqual(w.packet_db_unconfirmed,3)
                            self.assertIn('DB保存エラー',w.capture_state_label.text())
                        else:
                            w.stop();self.app.processEvents()
                            w.start()
                            w.bridge.publish(w.capture_session,PacketEvent(20,'RECV',127,b'\x7f\0abcd','TEST','flow'))
                            w.stop()
                        self.assertEqual(len(w.events),count+3+int(not fail))
                        self.assertIsNone(w.receiver)
                        self.assertIsNotNone(w.display_export)
                    finally:
                        release.set();self.wait_display_export()
                self.assertEqual(json.loads(target.read_text(encoding='utf-8')),json.loads(json.dumps(expected)))
                self.assertEqual(w.packet_progress()['awaiting_gui'],0)
                self.assertEqual(w.database_failed,fail)

    def test_close_cancels_generation_and_waits_for_pre_admitted_unemitted_packet(self):
        from threading import Event,Thread
        from gui.packet_delivery import PacketDelivery
        from events import PacketEvent
        w=self.window
        with patch('gui.main_window.load_lengths',return_value={127:6}),patch('gui.main_window.Receiver'):
            w.start()
        log=w.session_log.path
        entered=Event();release=Event()
        emit_entered=Event();emit_release=Event()
        event=PacketEvent(1,'RECV',127,b'\x7f\0abcd','TEST','flow')
        target=Path(self.log_folder.name)/'never-replaced.json'
        target.write_bytes(b'original')
        class Prepared:
            def build(self):
                entered.set()
                if not release.wait(3):raise RuntimeError('generation gate timeout')
                return {'observed':True}
        def delivery(*args):
            emit_entered.set()
            if not emit_release.wait(3):raise RuntimeError('delivery gate timeout')
            return PacketDelivery(*args)
        producer=None
        try:
            w.save_prepared_report(target,Prepared(),[],label='NPC')
            self.assertTrue(entered.wait(1))
            with patch('gui.packet_delivery.PacketDelivery',side_effect=delivery):
                producer=Thread(target=lambda:w.bridge.publish(1,event))
                producer.start()
                self.assertTrue(emit_entered.wait(1))
                w.close()
                self.assertFalse(w.workspace_closed)
                self.assertFalse(w.bridge.publish(1,event))
                self.assertEqual(w.db.db.execute('SELECT 1').fetchone()[0],1)
                emit_release.set();producer.join(2)
            import sqlite3
            with patch.object(w.db,'add',side_effect=sqlite3.OperationalError('private-payload')):
                self.app.processEvents()
            self.assertFalse(w.session_log.closed)
            self.assertEqual(w.events,[event])
            self.assertFalse(w.workspace_closed)
        finally:
            emit_release.set();release.set()
            if producer is not None:producer.join(2)
            self.wait_display_export();self.wait_window_closed()
        self.assertEqual(target.read_bytes(),b'original')
        self.assertTrue(w.database_failed)
        self.assertEqual(w.packet_db_unconfirmed,1)
        rows=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(rows[-1]['kind'],'session_end')
        self.assertTrue(any(row['kind']=='packet_database_error' for row in rows))
        self.assertNotIn('private-payload',log.read_text(encoding='utf-8'))
        self.assertEqual(w.packet_progress()['awaiting_gui'],0)

    def test_database_failure_stops_capture_preserves_pending_and_redacts_error(self):
        import sqlite3
        from events import PacketEvent
        w=self.window
        event=PacketEvent(1,'RECV',127,b'\x7f\0private-payload','TEST','flow')
        with patch('gui.main_window.load_lengths',return_value={127:4}), patch('gui.main_window.Receiver') as receiver:
            w.start()
            log=w.session_log.path
            w.bridge.publish(1,event)
            with patch.object(w.db,'add',side_effect=sqlite3.OperationalError('private-payload')) as add:
                w.bridge.publish(1,event)
                w.bridge.publish(1,event)
                add.assert_called_once()
            self.assertIsNone(w.receiver)
            receiver.return_value.stop.assert_called_once()
            self.assertEqual(len(w.events),3)
            counts=w.packet_progress()
            self.assertEqual((counts['published'],counts['accepted'],counts['awaiting_gui']),(3,3,0))
            self.assertEqual((counts['processed'],counts['db_confirmed'],counts['db_unconfirmed']),(3,1,2))
            self.assertFalse(w.start_button.isEnabled())
            w.start()
            self.assertEqual(receiver.call_count,1)
            self.assertIn('保存未確認 2件',w.capture_state_label.text())
            text=log.read_text(encoding='utf-8')
            self.assertIn('packet_database_error',text)
            self.assertNotIn('private-payload',text)

    def test_worker_delivery_waits_for_gui_and_preserves_order(self):
        from threading import Thread
        from events import PacketEvent
        w=self.window
        def publish():
            for index in range(4):
                w.bridge.publish(7,PacketEvent(index,'RECV',127,b'\x7f\0packet','TEST','flow'))
        worker=Thread(target=publish);worker.start();worker.join()
        self.assertEqual(w.bridge.snapshot()['awaiting_gui'],4)
        self.app.processEvents()
        self.assertEqual([event.timestamp for event in w.events],[0,1,2,3])
        self.assertEqual(w.display_sessions,[7]*4)
        self.assertEqual(w.packet_progress()['awaiting_gui'],0)

    def test_delivery_overflow_stops_capture_and_keeps_only_admitted_prefix(self):
        from threading import Thread
        from events import PacketEvent
        w=self.window
        w.bridge.max_pending=2
        with patch('gui.main_window.load_lengths',return_value={127:6}), patch('gui.main_window.Receiver') as receiver:
            w.start()
            log=w.session_log.path
            def publish():
                for index in range(5):w.bridge.publish(1,PacketEvent(index,'RECV',127,b'\x7f\0abcd','TEST','flow'))
            worker=Thread(target=publish);worker.start();worker.join()
            counts=w.bridge.snapshot()
            self.assertEqual((counts['awaiting_gui'],counts['pending_bytes'],counts['rejected']),(2,12,3))
            self.app.processEvents()
            self.assertEqual([e.timestamp for e in w.events],[0,1])
            receiver.return_value.stop.assert_called_once()
            self.assertFalse(w.start_button.isEnabled())
            self.assertIn('取得不完全',w.capture_state_label.text())
            self.assertEqual(w.packet_progress()['pending_bytes'],0)
            self.assertFalse(w.bridge.publish(1,PacketEvent(6,'RECV',127,b'\x7f\0abcd','TEST','flow')))
            w.start()
            self.assertEqual(receiver.call_count,1)
            rows=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            self.assertTrue(any(row.get('kind')=='packet_delivery_overflow' or row.get('type')=='packet_delivery_overflow' for row in rows))

    def test_delivery_byte_limit_and_concurrent_publishers_fail_closed(self):
        from concurrent.futures import ThreadPoolExecutor
        from events import PacketEvent
        from gui.packet_delivery import Bridge
        bridge=Bridge(max_pending=100,max_pending_bytes=30)
        event=PacketEvent(1,'RECV',127,b'\x7f\0abcd','TEST','flow')
        notices=[]
        bridge.overflow.connect(lambda:notices.append(True))
        with ThreadPoolExecutor(max_workers=3) as pool:
            admitted=list(pool.map(lambda _:bridge.publish(1,event),range(50)))
        self.app.processEvents()
        self.assertEqual(sum(admitted),5)
        counts=bridge.snapshot()
        self.assertEqual((counts['pending_bytes'],counts['awaiting_gui'],counts['rejected']),(30,5,45))
        self.assertEqual(len(notices),1)

    def test_stop_keeps_each_packet_committed_in_file_database(self):
        from contextlib import closing
        import sqlite3
        from storage.database import PacketDatabase
        from events import PacketEvent
        w=self.window
        path=Path(self.log_folder.name)/'packet-stop.sqlite3'
        w.db.close();w.db=PacketDatabase(path)
        for index in range(5):
            w.add_packet(PacketEvent(index,'RECV',0x7f,b'\x7f\0abcd','TEST','flow'))
        w.stop()
        self.assertFalse(w.db.db.in_transaction)
        self.assertEqual(len(w.events),5)
        with closing(sqlite3.connect(path)) as reader:
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM packets').fetchone()[0],5)
        self.assertEqual(w.db.synchronous,2)

    def test_display_and_standalone_diagnostics_freeze_text_and_protect_inputs(self):
        w = self.window
        for action, widget in ((w.save_display, w.display_log), (w.save_capture_log, w.capture_log)):
            destination = Path(self.log_folder.name) / 'visible.txt'
            widget.setPlainText('観測時点')
            def choose(*args):
                widget.setPlainText('追加観測')
                return str(destination), ''
            with patch('gui.main_window.QFileDialog.getSaveFileName', side_effect=choose):
                action()
            self.assertEqual(destination.read_text(encoding='utf-8'), '観測時点')
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
                with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                        patch('gui.main_window.QMessageBox.critical') as warning, \
                        patch('storage.observation_export.os.replace', side_effect=OSError('locked')) as replace:
                    action()
                    warning.assert_called_once()
                    self.assertEqual(replace.call_count, int(protection == 'replacement'))
                self.assertEqual(target.read_bytes(), before)

    def test_live_diagnostic_export_protects_selected_definitions_and_keeps_recording(self):
        w = self.window
        with patch('gui.main_window.load_lengths', return_value={0x90: 4}), \
                patch('gui.main_window.Receiver'):
            w.start()
            target = Path(self.log_folder.name) / 'selected-definitions.txt'
            target.write_text('0090 4', encoding='utf-8')
            w.path.setText(str(target))
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(target), '')), \
                    patch('gui.main_window.QMessageBox.critical') as warning:
                w.save_capture_log()
            warning.assert_called_once()
            self.assertEqual(target.read_text(encoding='utf-8'), '0090 4')
            w.show_capture_status('after rejected export')
            self.assertIn('after rejected export', w.session_log.path.read_text(encoding='utf-8'))
            self.assertFalse(w.session_log.error)
            w.stop()

    def test_capture_options_are_applied_and_locked_while_running(self):
        w = self.window
        self.assertTrue(w.capture_send.isChecked())
        self.assertFalse(w.record_stream.isChecked())
        self.assertFalse(w.pipe_enabled.isChecked())
        w.process.addItem('test.exe (PID 42)', 42)
        w.process.setCurrentIndex(1)
        self.assertFalse(w.port.isEnabled())
        w.attach_existing.setChecked(True)
        with patch('gui.main_window.load_lengths', return_value={0x90: 4}), \
             patch('gui.main_window.Receiver') as receiver:
            w.start()
            self.assertTrue(receiver.call_args.kwargs['allow_midstream'])
            self.assertFalse(w.process.isEnabled())
            self.assertFalse(w.attach_existing.isEnabled())
            self.assertFalse(w.definitions_browse.isEnabled())
            self.assertFalse(w.capture_send.isEnabled())
            w.stop()
            self.assertTrue(w.process.isEnabled())
            self.assertFalse(w.port.isEnabled())
        w.process.setCurrentIndex(0)
        self.assertTrue(w.port.isEnabled())

    def test_async_capture_failure_stays_visible_and_restores_start(self):
        w = self.window
        receiver = Mock()
        receiver.check_health.side_effect = RuntimeError('Npcap capture failed: test error')
        w.receiver = receiver
        w.poll_connections()
        self.assertIsNone(w.receiver)
        self.assertTrue(w.start_button.isEnabled())
        self.assertIn('test error', w.capture_log.toPlainText())
        self.assertIn('test error', w.capture_diagnostics.text())
        receiver.refresh_connections.assert_not_called()

    def test_diagnostic_log_can_be_saved_before_capture(self):
        w = self.window
        w.show_capture_status('sample framing error')
        path = Path(self.log_folder.name) / 'diagnostics.txt'
        with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(path), '')):
            w.save_capture_log()
        self.assertIn('sample framing error', path.read_text(encoding='utf-8'))

    def test_capture_creates_snapshot_and_exportable_jsonl(self):
        w = self.window
        w.record_stream.setChecked(True)
        with patch('gui.main_window.load_lengths', return_value={0x90: 4}), \
             patch('gui.main_window.Receiver') as receiver:
            w.start()
            self.assertIs(receiver.call_args.kwargs['recorder'], w.session_log)
            self.assertTrue(w.session_log.record_payload)
            w.show_capture_status('saved diagnostic')
            path = Path(self.log_folder.name) / 'export.jsonl'
            with patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                w.save_capture_log()
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertTrue(any(row.get('message') == 'saved diagnostic' for row in rows))
            self.assertTrue((w.session_log.directory / 'PacketLength.used.txt').exists())
            w.stop()
            self.assertTrue(w.session_log.closed)

    def test_panels_are_nonmodal_and_closing_them_does_not_stop_capture(self):
        w = self.window
        w.show()
        receiver = Mock()
        w.receiver = receiver
        w.update_capture_controls()
        w.settings_button.click()
        w.diagnostics_button.click()
        self.app.processEvents()
        self.assertTrue(w.settings_dialog.isVisible())
        self.assertTrue(w.diagnostics_dialog.isVisible())
        self.assertFalse(w.settings_dialog.isModal())
        self.assertFalse(w.diagnostics_dialog.isModal())
        w.settings_dialog.close()
        w.diagnostics_dialog.close()
        self.assertIs(w.receiver, receiver)
        receiver.stop.assert_not_called()

    def test_empty_manual_target_is_rejected_before_creating_a_log(self):
        w = self.window
        w.ip.clear()
        w.port.clear()
        with patch('gui.main_window.QMessageBox.critical') as message:
            w.start()
        message.assert_called_once()
        self.assertIsNone(w.receiver)
        self.assertIsNone(w.session_log)
        self.assertFalse(list(Path(self.log_folder.name).iterdir()))

    def test_main_status_is_brief_and_full_diagnostic_is_retained(self):
        w = self.window
        message = 'SEND framing stopped for endpoint: Unknown PacketID 0xFFFF; offset=10'
        w.show_capture_status(message)
        self.assertNotIn('0xFFFF', w.statusBar().currentMessage())
        self.assertIn('診断', w.statusBar().currentMessage())
        self.assertIn(message, w.capture_log.toPlainText())

    def test_capture_callback_retains_its_generation_after_restart(self):
        w = self.window
        w.process.addItem('test.exe (PID 42)', 42)
        w.process.setCurrentIndex(1)
        with patch('gui.main_window.load_lengths', return_value={0x9ff: -1}), \
             patch('gui.main_window.Receiver') as receiver:
            w.start()
            first_callback = receiver.call_args.args[3]
            first_callback(actor_packet())
            w.stop()
            w.start()
            second_callback = receiver.call_args.args[3]
            first_callback(actor_packet(name='旧観測'))
            second_callback(actor_packet(name='現観測'))
            self.assertEqual(w.display_sessions, [1, 1, 2])
            self.assertEqual(len(w.world.records()), 2)
            self.assertEqual(w.world.records(active_only=True)[0].name, '現観測')
            self.assertEqual(set(w.world_sources), {1, 2})
