import json
from pathlib import Path
import struct
from unittest.mock import patch

from PySide6.QtCore import QElapsedTimer, Qt
from PySide6.QtTest import QTest

from gui.offline import ReplayWorker
from reconstruction.auriga import AurigaRenderer
from storage.session_log import SessionLog
from tests.support.dialogue import packet
from tests.support.qt import WindowTestCase
from tests.support.world import actor_packet, map_packet
from tools.analyze_dialogues import analyze


class OfflineReplayTests(WindowTestCase):
    def test_project_records_loaded_catalogs_and_rejects_stale_save_or_runtime_change(self):
        from storage.project import CATALOG_PATHS,load_project,verify_project
        path,_=self.recording()
        with patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(path),'')):
            self.window.open_recording()
        child=self.window.offline_windows[-1]
        try:
            self.wait_until(lambda:child.save_project_action.isEnabled())
            child.workspace_tabs.setCurrentWidget(child.packet_page)
            destination=Path(self.log_folder.name)/'catalogs.gpa.json'
            with patch('gui.offline.QFileDialog.getSaveFileName',return_value=(str(destination),'')):
                child.save_project()
            document=load_project(destination);verify_project(document)
            self.assertEqual(set(document['catalogs']),set(CATALOG_PATHS))
            self.assertEqual(document['view']['tab'],5)
            self.assertEqual(document['catalogs']['skill_names']['sha256'],child.mob_skills_panel.names_sha256)
            before=destination.read_bytes()
            child.mob_skills_panel.names_sha256='0'*64
            with patch('gui.offline.QFileDialog.getSaveFileName',return_value=(str(destination),'')), \
                 patch('gui.offline.QMessageBox.critical') as warning:
                child.save_project()
            warning.assert_called_once()
            self.assertEqual(destination.read_bytes(),before)
            different=Path(self.log_folder.name)/'different.json';different.write_text('{}')
            count=len(self.window.offline_windows)
            with patch.dict(CATALOG_PATHS,{'reference_names':different}), \
                 patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(destination),'')), \
                 patch('gui.main_window.QMessageBox.critical') as warning:
                self.window.open_project()
            warning.assert_called_once()
            self.assertEqual(len(self.window.offline_windows),count)
        finally:child.close()

    def test_project_checks_loaded_catalog_before_publishing_and_marks_legacy_version(self):
        from gui.offline import OfflineWindow
        path,_=self.recording()
        with patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(path),'')):
            self.window.open_recording()
        child=self.window.offline_windows[-1]
        self.wait_until(lambda:child.save_project_action.isEnabled())
        destination=Path(self.log_folder.name)/'pinned.gpa.json'
        with patch('gui.offline.QFileDialog.getSaveFileName',return_value=(str(destination),'')):
            child.save_project()
        child.close()
        with patch.object(OfflineWindow,'loaded_catalog_hashes',return_value={'skill_names':'0'*64}), \
             patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(destination),'')):
            self.window.open_project()
            failed=self.window.offline_windows[-1]
            try:
                self.wait_until(lambda:failed.capture_state_label.text().startswith('再解析失敗'))
                self.assertFalse(failed.events)
                self.assertFalse(failed.save_project_action.isEnabled())
            finally:failed.close()
        document=json.loads(destination.read_text(encoding='utf-8'));document.pop('catalogs')
        legacy=Path(self.log_folder.name)/'legacy.gpa.json'
        legacy.write_text(json.dumps(document),encoding='utf-8')
        with patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(legacy),'')):
            self.window.open_project()
        restored=self.window.offline_windows[-1]
        try:
            self.wait_until(lambda:restored.save_project_action.isEnabled())
            self.assertIn('名称辞書版未記録',restored.windowTitle())
            self.assertTrue(restored.events)
            self.assertFalse(self.window.events)
        finally:restored.close()

    def test_owner_close_waits_for_replay_worker_and_child_rejects_new_exports(self):
        from threading import Event
        path,_=self.recording(2)
        original_bytes=path.read_bytes()
        entered=Event();release=Event()
        original_run=ReplayWorker.run
        def paused(worker):
            entered.set()
            if release.wait(3):original_run(worker)
        with patch.object(ReplayWorker,'run',new=paused), \
                patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(path),'')):
            try:
                self.window.open_recording()
                child=self.window.offline_windows[0]
                self.assertTrue(entered.wait(1))
                self.window.close()
                self.assertFalse(self.window.workspace_closed)
                self.assertTrue(child.workspace_closing)
                self.assertEqual(self.window.db.db.execute('SELECT 1').fetchone()[0],1)
                with patch('gui.main_window.QFileDialog.getSaveFileName') as dialog:
                    child.save_display()
                dialog.assert_not_called()
            finally:
                release.set();self.wait_window_closed()
        self.assertEqual(self.window.offline_windows,[])
        self.assertEqual(path.read_bytes(),original_bytes)

    def test_owner_close_waits_for_offline_text_export_worker(self):
        from threading import Event
        from unittest.mock import PropertyMock
        from storage.observation_export import save_observation_chunks
        import sqlite3
        path,_=self.recording(2)
        with patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(path),'')):
            self.window.open_recording()
        child=self.window.offline_windows[0]
        self.wait_until(lambda:child.save_project_action.isEnabled())
        target=Path(self.log_folder.name)/'closing-export.txt'
        target.write_bytes(b'original')
        entered=Event();release=Event()
        def paused(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('worker gate timeout')
            return save_observation_chunks(*args,**kwargs)
        def owner_database_closed():
            try:self.window.db.db.execute('SELECT 1')
            except sqlite3.ProgrammingError:return True
            return False
        with patch('gui.observation_save.ObservationTextSnapshot.needs_worker',new_callable=PropertyMock,return_value=True), \
                patch('gui.observation_save.save_observation_chunks',side_effect=paused), \
                patch('gui.main_window.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            try:
                child.save_display()
                self.assertTrue(entered.wait(1))
                self.window.close()
                self.assertIn(child,self.window.offline_windows)
                self.assertIsNotNone(child.display_export)
                self.assertFalse(owner_database_closed())
            finally:
                release.set()
                self.wait_until(owner_database_closed)
        self.assertEqual(self.window.offline_windows,[])
        self.assertEqual(target.read_bytes(),b'original')
        self.assertFalse(list(Path(self.log_folder.name).glob('*.tmp')))

    def test_database_failure_does_not_mark_partial_replay_complete(self):
        import sqlite3
        path,_=self.recording(2)
        original=path.read_bytes()
        with patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(path),'')):
            self.window.open_recording()
        child=self.window.offline_windows[0]
        try:
            with patch.object(child.db,'add',side_effect=sqlite3.OperationalError('failed')):
                self.wait_until(lambda: child.database_failed)
                self.assertFalse(child.apply_timer.isActive())
                self.assertFalse(child.save_project_action.isEnabled())
                self.assertNotIn('再解析完了',child.capture_state_label.text())
                self.assertEqual(len(child.events),1)
                self.assertEqual(child.packet_progress()['db_unconfirmed'],1)
        finally:child.close()
        self.assertEqual(path.read_bytes(),original)

    def test_saved_actor_appearance_replays_initial_display_and_class_changes(self):
        from dataclasses import replace
        from tools.analyze_session import analyze as analyze_session
        from reconstruction.npc_bundle import build_npc_bundle
        definitions={0x91:22,0x9ff:-1,0x1b0:11,0x80:7}
        first=actor_packet(name='Guide')
        raw=bytearray(first.raw)
        struct.pack_into('<H',raw,23,4001)
        struct.pack_into('<H',raw,25,3)
        raw[62]=1
        first=replace(first,raw=bytes(raw))
        later=bytearray(raw);struct.pack_into('<H',later,23,139)
        change=packet(0x1b0,struct.pack('<IBI',42,0,139)).raw
        removed=packet(0x80,struct.pack('<IB',42,0)).raw
        payload=map_packet('test.gat').raw+first.raw+first.raw+change+removed+bytes(later)
        log=SessionLog(self.log_folder.name,definitions,record_payload=True)
        log.write('capture_format',transport='tcp_segments',capture_send=True)
        incoming=('192.0.2.1',5121,'192.0.2.2',50000)
        outgoing=('192.0.2.2',50000,'192.0.2.1',5121)
        log.write('tcp_segment',endpoints=outgoing,sequence=10,flags=2,data=b'',timestamp=0,direction='SEND')
        log.write('tcp_segment',endpoints=incoming,sequence=30,flags=18,data=b'',timestamp=0,direction='RECV')
        # Split inside an appearance packet to exercise framing on replay.
        split=40
        for seq,data in ((31,payload[:split]),(31+split,payload[split:])):
            log.write('tcp_segment',endpoints=incoming,sequence=seq,flags=16,data=data,timestamp=1,direction='RECV')
        log.close()
        original=log.path.read_bytes()
        report=analyze_session(log.path,definitions)
        entities=report['world']['entities']
        self.assertEqual(len(entities),2)
        for entity in entities:
            self.assertEqual(entity['initial_display']['class_id'],4001)
            self.assertEqual(entity['initial_display']['appearance_data']['hair_style'],3)
            self.assertEqual(entity['class_id'],139)
        self.assertEqual(len(report['npc_display_candidates']),1)
        self.assertIn('setnpcdisplay "Guide",139;',report['npc_display_candidates'][0]['auriga'])
        expected=build_npc_bundle(entities,[])['auriga']
        self.assertEqual(expected.count('OnInit:'),1)
        self.assertEqual(expected.count('setnpcdisplay "Guide",4001,1,3,0,0,0,0,0,0,0;'),1)
        with patch('gui.main_window.QFileDialog.getOpenFileName',return_value=(str(log.path),'')):
            self.window.open_recording()
        child=self.window.offline_windows[0]
        try:
            self.wait_until(lambda: child.save_project_action.isEnabled())
            self.assertEqual(len(child.events),6)
            gui_entities=child.world.snapshot('NPC')['entities']
            self.assertEqual([e['initial_display'] for e in gui_entities],
                             [e['initial_display'] for e in entities])
            self.assertEqual(build_npc_bundle(gui_entities,[])['auriga'],expected)
            self.assertEqual(child.display_log.toPlainText().count('初回観測'),1)
            self.assertIn('class: 4001 → 139',child.display_log.toPlainText())
        finally:
            child.close()
        self.assertEqual(log.path.read_bytes(),original)

    def test_one_pass_report_matches_individual_analysis_and_protects_saved_evidence(self):
        from tools.analyze_session import analyze as analyze_session, save_report
        from tools.analyze_entities import analyze as analyze_entities
        from tools.analyze_player import analyze as analyze_player
        from tools.analyze_skills import analyze as analyze_skills
        from tools.merge_dialogues import merge
        from storage.project import fingerprint
        path, definitions = self.recording(1)
        report = analyze_session(path, definitions)
        self.assertEqual(report['source_sha256'], fingerprint(path, 128 * 1024 * 1024))
        self.assertEqual(report['world']['entities'], analyze_entities(path, definitions)['entities'])
        self.assertEqual(report['player']['states'], analyze_player(path, definitions)['states'])
        self.assertEqual(report['skills']['observations'], analyze_skills(path, definitions)['observations'])
        individual = analyze(path, definitions)
        self.assertEqual(report['dialogues']['conversations'], individual['conversations'])
        self.assertEqual(report['merged_dialogues']['auriga'], merge([path], definitions)['auriga'])
        self.assertEqual(report['transport_quality'], 'not_verified')
        self.assertEqual(report['quality']['capture_completeness'], 'not_verified')
        self.assertEqual(report['quality']['issue_counts']['world'], report['world']['issue_count'])
        self.assertIn('dialogue_review', report)
        self.assertEqual(report['measurements']['packet_count'], sum(report['replay']['packet_counts'].values()))
        destination = Path(self.log_folder.name) / 'session-analysis.json'
        save_report(destination, report)
        previous = destination.read_bytes()
        with patch('tools.analyze_session.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                save_report(destination, report)
        self.assertEqual(destination.read_bytes(), previous)
        with self.assertRaises(ValueError):
            save_report(path, report)
        source_reads = 0
        def changed_source(candidate, limit):
            nonlocal source_reads
            digest = fingerprint(candidate, limit)
            if Path(candidate).resolve() == path.resolve():
                source_reads += 1
                return digest if source_reads == 1 else 'changed-source'
            return digest
        with patch('tools.analyze_session.fingerprint', side_effect=changed_source):
            with self.assertRaisesRegex(ValueError, '生ログ'):
                analyze_session(path, definitions)


    def test_saved_ignore_settings_apply_to_replay_without_changing_generated_dialogue(self):
        from parser.ignorepacket import IgnorePacket
        path, definitions = self.recording()
        settings = IgnorePacket(ids=frozenset({0xb4}))
        with patch.object(IgnorePacket, 'load', return_value=settings), \
                patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            self.window.open_recording()
        child = self.window.offline_windows[0]
        try:
            self.wait_until(lambda: child.save_project_action.isEnabled())
            self.assertEqual(len(child.events), len(child.observation_tags))
            self.assertTrue(any(event.packet_id == 0xb4 for event in child.events))
            expected = analyze(path, definitions)['auriga'][0]
            self.assertEqual(child.dialogue_panel.code.toPlainText(), expected)
            before = child.display_log.toPlainText()
            child.ignorepacket = IgnorePacket()
            child.rebuild_display_log()
            self.assertNotEqual(child.display_log.toPlainText(), before)
            self.assertEqual(child.dialogue_panel.code.toPlainText(), expected)
        finally:
            child.close()

    def test_project_roundtrip_restores_view_notes_and_rejects_changed_inputs(self):
        path, definitions = self.recording()
        with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            self.window.open_recording()
        child = self.window.offline_windows[0]
        self.wait_until(lambda: child.save_project_action.isEnabled())
        child.filter.setText('00B4')
        child.display_timestamps.setChecked(True)
        child.workspace_tabs.setCurrentWidget(child.dialogue_panel)
        child.project_note = '同じ選択肢を再観測する'
        project_path = Path(self.log_folder.name) / 'test.gpa.json'
        with patch('gui.offline.QFileDialog.getSaveFileName', return_value=(str(project_path), '')):
            child.save_project()
        self.assertTrue(project_path.is_file())
        code = child.dialogue_panel.code.toPlainText()
        child.close()
        with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(project_path), '')):
            self.window.open_project()
        restored = self.window.offline_windows[0]
        try:
            self.wait_until(lambda: restored.save_project_action.isEnabled())
            self.assertEqual(restored.filter.text(), '00B4')
            self.assertTrue(restored.display_timestamps.isChecked())
            self.assertIs(restored.workspace_tabs.currentWidget(), restored.dialogue_panel)
            self.assertEqual(restored.project_note, '同じ選択肢を再観測する')
            self.assertEqual(restored.dialogue_panel.code.toPlainText(), code)
            self.assertEqual(len(self.window.events), 0)
        finally:
            restored.close()
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(project_path), '')):
            self.window.open_project()
        failed = self.window.offline_windows[0]
        try:
            self.wait_until(lambda: failed.capture_state_label.text().startswith('再解析失敗'))
            self.assertFalse(failed.events)
            self.assertFalse(failed.save_project_action.isEnabled())
        finally:
            failed.close()
        self.assertFalse(self.window.events)

    def recording(self, choice=None):
        definitions = {0x91: 22, 0x9ff: -1, 0x90: 7, 0xb4: -1, 0xb6: 6}
        if choice is not None:
            definitions.update({0xb7: -1, 0xb8: 7})
        log = SessionLog(self.log_folder.name, definitions, record_payload=True)
        log.write('capture_format', transport='tcp_segments', capture_send=True)
        initial = map_packet().raw + actor_packet().raw
        opened = packet(0x90, struct.pack('<IB', 42, 1), 'SEND').raw
        reply = packet(0xb4, struct.pack('<I', 42) + b'hello\0').raw + packet(0xb6, struct.pack('<I', 42)).raw
        incoming, outgoing = ('server', 1, 'client', 2), ('client', 2, 'server', 1)
        segments = [
            (outgoing, 10, 2, b'', 0, 'SEND'), (incoming, 30, 18, b'', 0, 'RECV'),
            (incoming, 31, 16, initial, 1, 'RECV'), (outgoing, 11, 16, opened, 2, 'SEND')]
        if choice is None:
            segments.append((incoming, 31 + len(initial), 16, reply, 3, 'RECV'))
        else:
            prompt = packet(0xb7, struct.pack('<I', 42) + b'one:two:\0').raw
            answer = packet(0xb8, struct.pack('<IB', 42, choice), 'SEND').raw
            reply = (packet(0xb4, struct.pack('<I', 42) + f'result-{choice}\0'.encode()).raw
                     + packet(0xb6, struct.pack('<I', 42)).raw)
            segments.extend([(incoming, 31 + len(initial), 16, prompt, 3, 'RECV'),
                             (outgoing, 11 + len(opened), 16, answer, 4, 'SEND'),
                             (incoming, 31 + len(initial) + len(prompt), 16, reply, 5, 'RECV')])
        for endpoints, seq, flags, data, timestamp, direction in segments:
            log.write('tcp_segment', endpoints=endpoints, sequence=seq, flags=flags, data=data,
                      timestamp=timestamp, direction=direction)
        log.close()
        return log.path, definitions

    def test_multiple_logs_keep_scopes_merge_paths_and_deduplicate_copies(self):
        from tools.merge_dialogues import merge
        from gui.offline import MultiReplayWorker
        first, definitions = self.recording(1)
        second, _ = self.recording(2)
        duplicate = first.with_name('copy.jsonl')
        duplicate.write_bytes(first.read_bytes())
        with patch('gui.main_window.QFileDialog.getOpenFileNames',
                   return_value=([str(first), str(duplicate), str(second), str(first)], '')):
            self.window.open_recordings()
        child = self.window.offline_windows[0]
        try:
            self.wait_until(lambda: child.capture_state_label.text().startswith('再解析完了'))
            self.assertEqual(len(child.events), 14)
            self.assertEqual(set(child.display_sessions), {1, 3})
            self.assertEqual(child.world_sources, {1: str(first.resolve()), 3: str(second.resolve())})
            self.assertEqual(len(child.replay_report['duplicate_logs']), 1)
            report = child.dialogue_panel.merged_report()
            expected = merge([first, second], definitions)
            self.assertEqual(len(report['groups']), 1)
            self.assertEqual(len(report['groups'][0]['contributions']), 2)
            child.dialogue_panel.merge_checkbox.setChecked(True)
            self.assertEqual(child.dialogue_panel.code.toPlainText(), expected['auriga'][0])
            self.assertTrue(child.save_project_action.isEnabled())
            child.project_note = '複数ログの比較'
            child.workspace_tabs.setCurrentWidget(child.dialogue_panel)
            project_path = Path(self.log_folder.name) / 'multiple.gpa.json'
            with patch('gui.offline.QFileDialog.getSaveFileName', return_value=(str(project_path), '')):
                child.save_project()
            saved = json.loads(project_path.read_text(encoding='utf-8'))
            self.assertEqual(saved['schema'], 2)
            self.assertEqual([row['capture_session'] for row in saved['sources']], [1, 3])
            with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(project_path), '')):
                self.window.open_project()
            restored = self.window.offline_windows[-1]
            try:
                self.wait_until(lambda: restored.save_project_action.isEnabled())
                self.assertEqual(restored.world_sources, child.world_sources)
                self.assertEqual(restored.dialogue_panel.code.toPlainText(), child.dialogue_panel.code.toPlainText())
                self.assertEqual(restored.project_note, child.project_note)
                self.assertEqual(len(restored.events), 14)
            finally:
                restored.close()
            original_second = second.read_bytes()
            second.write_bytes(original_second + b'\n')
            with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(project_path), '')):
                self.window.open_project()
            rejected = self.window.offline_windows[-1]
            try:
                self.wait_until(lambda: rejected.capture_state_label.text().startswith('再解析失敗'))
                self.assertFalse(rejected.events)
                self.assertFalse(rejected.save_project_action.isEnabled())
            finally:
                rejected.close()
                second.write_bytes(original_second)
            used = second.with_name('PacketLength.used.txt')
            original_used = used.read_bytes()
            used.write_bytes(original_used + b'\n')
            count = len(self.window.offline_windows)
            with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(project_path), '')), \
                 patch('gui.main_window.QMessageBox.critical') as message:
                self.window.open_project()
            self.assertEqual(len(self.window.offline_windows), count)
            message.assert_called_once()
            used.write_bytes(original_used)
            self.assertFalse(self.window.events)
        finally:
            child.close()
        # A later invalid log must not publish the earlier staged result.
        bad = first.with_name('invalid.jsonl')
        bad.write_text('not json', encoding='utf-8')
        worker = MultiReplayWorker([(first, definitions, first.with_name('PacketLength.used.txt')),
                                    (bad, definitions, first.with_name('PacketLength.used.txt'))])
        results, errors = [], []
        worker.loaded.connect(results.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertFalse(results)
        self.assertTrue(errors)
        conflicting = dict(definitions)
        conflicting[0xb4] = 10
        worker = MultiReplayWorker([(first, definitions, first.with_name('PacketLength.used.txt')),
                                    (duplicate, conflicting, first.with_name('PacketLength.used.txt'))])
        worker.loaded.connect(results.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertFalse(results)
        self.assertEqual(len(errors), 2)

    def wait_until(self, predicate):
        timer = QElapsedTimer()
        timer.start()
        while not predicate() and timer.elapsed() < 5000:
            self.app.processEvents()
            QTest.qWait(1)
        self.assertTrue(predicate(), 'Offline replay did not finish')

    def test_offline_replay_matches_cli_and_preserves_live_workspace(self):
        path, definitions = self.recording()
        original = path.read_bytes()
        self.window.add_packet(packet(0xb4, struct.pack('<I', 99) + b'live\0'))
        with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            self.window.open_recording()
        child = self.window.offline_windows[0]
        try:
            self.wait_until(lambda: child.capture_state_label.text().startswith('再解析完了'))
            expected = analyze(path, definitions)
            self.assertEqual(AurigaRenderer().render(child.dialogues.sessions[0]), expected['auriga'][0])
            self.assertEqual(len(child.events), 5)
            self.assertEqual(child.replay_report['packet_counts_by_direction'], expected['replay']['packet_counts_by_direction'])
            self.assertEqual(child.world_sources, {1: str(path.resolve())})
            self.assertEqual(len(self.window.events), 1)
            self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 1)
            self.assertEqual(child.db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0], 5)
            self.assertFalse(child.start_button.isEnabled())
            with patch('gui.main_window.Receiver') as receiver:
                child.start()
            receiver.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(Path(child.path.text()), path.with_name('PacketLength.used.txt'))
        finally:
            child.close()

    def test_worker_limits_cancellation_and_bad_input_never_publish_partial_packets(self):
        path, definitions = self.recording()
        results, errors = [], []
        worker = ReplayWorker(path, definitions, max_packets=1)
        worker.loaded.connect(results.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertFalse(results)
        self.assertIn('上限', errors[-1])
        bad = Path(self.log_folder.name) / 'bad.jsonl'
        bad.write_text('{"secret":"private-dialogue"}\nnot json', encoding='utf-8')
        worker = ReplayWorker(bad, definitions)
        worker.loaded.connect(results.append)
        worker.failed.connect(errors.append)
        worker.run()
        self.assertFalse(results)
        self.assertNotIn('private-dialogue', errors[-1])
        worker = ReplayWorker(path, definitions)
        worker.loaded.connect(results.append)
        worker.started.connect(worker.requestInterruption, Qt.DirectConnection)
        worker.start()
        worker.wait(5000)
        self.app.processEvents()
        self.assertFalse(results)
        shortened = dict(definitions)
        del shortened[0xb4]
        worker = ReplayWorker(path, shortened)
        worker.loaded.connect(results.append)
        worker.run()
        events, report = results[0]
        self.assertEqual(len(events), 3)
        self.assertEqual(report['failed_connections'], 1)
        self.assertEqual(len(report['errors']), 1)

    def test_open_while_capturing_is_rejected_and_cancel_keeps_original_data(self):
        path, definitions = self.recording()
        self.window.receiver = object()
        with patch('gui.main_window.QFileDialog.getOpenFileName') as dialog:
            self.window.open_recording()
        dialog.assert_not_called()
        self.window.receiver = None
        self.window.add_packet(packet(0xb4, struct.pack('<I', 99) + b'live\0'))
        with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            self.window.open_recording()
        child = self.window.offline_windows[0]
        child.cancel_replay()
        self.wait_until(lambda: not self.window.offline_windows)
        self.assertEqual(len(self.window.events), 1)
