"""Isolated, bounded offline replay. Worker stages packets; only Qt owns widgets."""
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import QProgressDialog, QFileDialog, QMessageBox, QInputDialog

from gui.main_window import MainWindow
from parser.display import DisplayProfile, ReceiveDisplay
from tools.replay_capture import replay, ReplayCancelled
from storage.project import fingerprint, verify_project, save_project, save_multiple_project, CATALOG_PATHS
from parser.definitions import load_lengths
from reconstruction.auriga import DEFAULT_DIALOGUE_PROFILE


class ReplayLimitError(ValueError):
    pass


class ReplayWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, path, definitions, parent=None, *, max_packets=20000, max_packet_bytes=32 * 1024 * 1024,
                 project=None, cancelled=None):
        super().__init__(parent)
        self.path, self.definitions = Path(path), dict(definitions)
        self.max_packets, self.max_packet_bytes = max_packets, max_packet_bytes
        self.project = project
        self.cancelled_check = cancelled

    def is_cancelled(self):
        return self.isInterruptionRequested() or bool(self.cancelled_check and self.cancelled_check())

    def run(self):
        events, byte_count = [], 0
        def collect(event):
            nonlocal byte_count
            if len(events) >= self.max_packets or byte_count + len(event.raw) > self.max_packet_bytes:
                raise ReplayLimitError()
            events.append(event)
            byte_count += len(event.raw)
        def progress(line):
            if line > 200000:
                raise ReplayLimitError()
            self.progress.emit(line)
        try:
            if self.path.stat().st_size > 128 * 1024 * 1024:
                raise ReplayLimitError()
            source_hash = fingerprint(self.path, 128 * 1024 * 1024, self.is_cancelled)
            if self.project:
                verify_project(self.project, self.is_cancelled)
            report = replay(self.path, self.definitions, collect,
                            is_cancelled=self.is_cancelled, on_progress=progress,
                            max_line_chars=2 * 1024 * 1024, max_input_chars=128 * 1024 * 1024)
            if self.is_cancelled():
                return
            if fingerprint(self.path, 128 * 1024 * 1024, self.is_cancelled) != source_hash:
                raise ValueError('Input changed during replay')
            if self.project:
                verify_project(self.project, self.is_cancelled)
            text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(self.definitions.items()))
            report['definitions_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            report['source_sha256'] = source_hash
            self.loaded.emit((events, report))
        except ReplayCancelled:
            return
        except ReplayLimitError:
            self.failed.emit('GUI再生の上限に到達しました。CLIで対象範囲を確認してください。')
        except Exception:
            if self.is_cancelled():
                return
            # External record values and plaintext never become diagnostic text.
            self.failed.emit('プロジェクトの参照ファイルが不足・変更された可能性があります。生ログから開き直してください。'
                             if self.project else
                             '再解析できません。生バイト記録の有無、JSONL形式、長さ定義を確認してください。')


class MultiReplayWorker(ReplayWorker):
    """Stage each log independently, publishing only a complete bounded set."""
    def __init__(self, inputs, parent=None, project=None):
        super().__init__(inputs[0][0], inputs[0][1], parent, project=project)
        self.inputs = inputs

    def run(self):
        events, reports, duplicates, seen = [], [], [], {}
        byte_count = 0
        try:
            if len(self.inputs) > 20 or sum(Path(row[0]).stat().st_size for row in self.inputs) > 128 * 1024 * 1024:
                raise ReplayLimitError()
            if self.project:
                verify_project(self.project, self.is_cancelled)
            for ordinal, (path, definitions, definitions_path) in enumerate(self.inputs):
                session = self.project['sources'][ordinal]['capture_session'] if self.project else ordinal + 1
                if self.is_cancelled():
                    return
                identity = (fingerprint(path, 128 * 1024 * 1024, self.is_cancelled), tuple(sorted(definitions.items())))
                if identity[0] in seen:
                    if seen[identity[0]] != identity[1]:
                        raise ValueError('Identical recordings have conflicting definitions')
                    duplicates.append(str(Path(path).resolve()))
                    continue
                worker = ReplayWorker(path, definitions, max_packets=self.max_packets - len(events),
                                      max_packet_bytes=self.max_packet_bytes - byte_count, cancelled=self.is_cancelled)
                results, failures = [], []
                worker.loaded.connect(results.append, Qt.DirectConnection)
                worker.failed.connect(failures.append, Qt.DirectConnection)
                worker.progress.connect(self.progress.emit, Qt.DirectConnection)
                worker.run()
                if self.is_cancelled():
                    return
                if failures or not results:
                    raise ValueError('A log could not be replayed')
                packets, report = results[0]
                if report['source_sha256'] != identity[0]:
                    raise ValueError('Input changed during replay')
                seen[identity[0]] = identity[1]
                events.extend((session, packet) for packet in packets)
                byte_count += sum(len(packet.raw) for packet in packets)
                reports.append(dict(report, capture_session=session,
                                    definitions_path=str(Path(definitions_path).resolve())))
            if self.is_cancelled():
                return
            if self.project:
                verify_project(self.project, self.is_cancelled)
            self.loaded.emit((events, dict(sources=reports, duplicate_logs=duplicates,
                failed_connections=sum(row['failed_connections'] for row in reports),
                session_end_present=all(row['session_end_present'] for row in reports))))
        except Exception:
            if not self.is_cancelled():
                self.failed.emit('複数ログを再解析できません。形式・生バイト・定義・合計上限を確認してください。結果は公開しません。')


class OfflineWindow(MainWindow):
    def __init__(self, path, definitions, definitions_path, profiles, owner, project=None, inputs=None):
        receive_profile = DisplayProfile.load(profiles['RECV'])
        send_profile = DisplayProfile.load(profiles['SEND'])
        super().__init__(offline=True)
        self.owner = owner
        self.source_path = Path(path).resolve()
        self.path.setText(str(Path(definitions_path).resolve()))
        self.display_profile_paths = dict(profiles)
        self.display_input_paths = dict(profiles)
        self.display_path.setText(profiles['RECV'])
        self.presenter = ReceiveDisplay(receive_profile)
        self.send_presenter = ReceiveDisplay(send_profile, direction='SEND')
        self.setWindowTitle(f'保存ログの再解析 — {self.source_path.parent.name}')
        self.entity_timer.stop()
        self.multiple = inputs is not None
        self.worker = (MultiReplayWorker(inputs, self, project=project) if inputs is not None else
                       ReplayWorker(self.source_path, definitions, self, project=project))
        if self.multiple:
            self.setWindowTitle(f'保存ログの比較 — {len(inputs)}ファイル')
        self.worker.loaded.connect(self._loaded)
        self.worker.failed.connect(self._failed)
        self.worker.progress.connect(lambda line: self.progress.setLabelText(f'生ログを読み取り中: {line}行'))
        self.worker.finished.connect(self._worker_finished)
        self.progress = QProgressDialog('生ログを読み取り中', '取消', 0, 0, self)
        self.progress.setAutoClose(False)
        self.progress.setMinimumDuration(0)
        self.progress.canceled.connect(self.cancel_replay)
        self.apply_timer = QTimer(self)
        self.apply_timer.timeout.connect(self._apply_batch)
        self.staged_events = []
        self.replay_report = None
        self.applied = 0
        self.closing = False
        self.cancelled = False
        self.project = project
        if project and not project.get('catalogs'):
            self.setWindowTitle(self.windowTitle()+'（名称辞書版未記録）')
        self.project_note = project['note'] if project else ''

    def begin_replay(self):
        self.capture_state_label.setText('保存ログ読込中')
        self.progress.show()
        self.worker.start()

    def loaded_catalog_hashes(self):
        expected={'skill_names':self.mob_skills_panel.names_sha256,'client_names':self.client_names['_sha256'],'navigation':self.navigation['_sha256']}
        for renderer in (self.presenter,self.send_presenter):
            for key,attr in (('skill_units','unit_catalog'),('reference_names','reference_names')):
                catalog=getattr(renderer.profile,attr)
                if catalog is not None:
                    sha=catalog['_sha256']
                    if key in expected and expected[key]!=sha:
                        raise ValueError('送受信の名称辞書が異なります。表示書式を再読込してください。')
                    expected[key]=sha
        return expected

    def _loaded(self, result):
        if self.cancelled or self.closing:
            return
        if self.project and self.project.get('catalogs'):
            try:
                loaded=self.loaded_catalog_hashes()
                if set(loaded)-set(self.project['catalogs']):
                    self.setWindowTitle(self.windowTitle()+'（名称辞書版一部未記録）')
                if any(loaded.get(key)!=ref['sha256'] for key,ref in self.project['catalogs'].items()):
                    raise ValueError('読み込み済みの名称辞書が保存時と異なります。')
            except ValueError:
                self._failed('読み込み済みの名称辞書が保存時と異なります。再読込してください。')
                return
        self.staged_events, self.replay_report = result
        self.capture_session = 1
        if self.multiple:
            self.world_sources.update({row['capture_session']: row['source_log'] for row in self.replay_report['sources']})
        else:
            self.world_sources[1] = str(self.source_path)
        self.progress.setLabelText('観測データを再構築中')
        self.progress.setRange(0, max(1, len(self.staged_events)))
        self.apply_timer.start(0)

    def _apply_batch(self):
        if self.cancelled or self.closing:
            return
        try:
            end = min(self.applied + 100, len(self.staged_events))
            for event in self.staged_events[self.applied:end]:
                session = event[0] if self.multiple else 1
                if session != self.capture_session:
                    self.capture_session = session
                    self.presenter.reset()
                    self.send_presenter.reset()
                self.add_packet(event if self.multiple else (1, event))
                if self.database_failed:
                    self.apply_timer.stop()
                    self.progress.hide()
                    self.save_project_action.setEnabled(False)
                    self.project_note_action.setEnabled(False)
                    self.refresh_entity_views()
                    return
            self.applied = end
            self.progress.setValue(end)
            if end == len(self.staged_events):
                self.apply_timer.stop()
                self.staged_events = []
                self.progress.hide()
                self.refresh_entity_views()
                self.entity_timer.start()
                report = self.replay_report
                state = f'再解析完了 / {len(self.events)}件 / 停止接続 {report["failed_connections"]}'
                if not report['session_end_present']:
                    state += ' / 記録終端なし'
                self.capture_state_label.setText(state)
                self.capture_diagnostics.setText(json.dumps(report, ensure_ascii=False, indent=2))
                self.mode_summary.setText(f'保存ログ: {len(report["sources"])}件 / 各ログの出典は診断で確認'
                                          if self.multiple else f'保存ログ: {self.source_path}')
                self.save_project_action.setEnabled(True)
                self.project_note_action.setEnabled(True)
                if self.project:
                    view = self.project['view']
                    self.filter.setText(view['filter'])
                    self.display_timestamps.setChecked(view['timestamps'])
                    self.display_unmapped.setChecked(view['unmapped'])
                    self.workspace_tabs.setCurrentIndex(view['tab'])
                    self.dialogue_panel.selection.setCurrentIndex(view['conversation'])
                    self.dialogue_panel.merge_checkbox.setChecked(view['merged'])
        except Exception:
            self._failed('観測データの再構築に失敗しました。元の観測画面と入力ログは変更していません。')

    def _failed(self, message):
        if self.cancelled or self.closing:
            return
        self.apply_timer.stop()
        self.progress.hide()
        self.staged_events = []
        self.save_project_action.setEnabled(False)
        self.project_note_action.setEnabled(False)
        self.capture_state_label.setText('再解析失敗（この画面の結果は未完成）')
        self.show_capture_status(message)

    def edit_project_note(self):
        note, accepted = QInputDialog.getMultiLineText(self, '作業注記', '観測条件・次に確認する項目', self.project_note)
        if accepted and len(note) <= 8192:
            self.project_note = note
        elif accepted:
            QMessageBox.warning(self, '作業注記が長すぎます', '作業注記は8192文字以内にしてください。')

    def save_project(self):
        if self.history_tasks.busy or self.history_view_stale:
            self.statusBar().showMessage('表示更新を完了してください。取消後は「表示を再更新」を実行してください。')
            return
        if not self.save_project_action.isEnabled():
            return
        destination, _ = QFileDialog.getSaveFileName(self, '作業プロジェクトを保存',
                                                    'observation.gpa.json', 'Project (*.gpa.json)')
        if not destination:
            return
        try:
            profiles = dict(self.display_profile_paths)
            for source in (self.replay_report['sources'] if self.multiple else
                           [dict(definitions_path=self.path.text(), definitions_sha256=self.replay_report['definitions_sha256'])]):
                definitions = load_lengths(source['definitions_path'])
                normalized = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
                if hashlib.sha256(normalized.encode('utf-8')).hexdigest() != source['definitions_sha256']:
                    raise ValueError('使用中の長さ定義が変更されています。')
            for direction, renderer in (('RECV', self.presenter), ('SEND', self.send_presenter)):
                candidate = DisplayProfile.load(profiles[direction])
                for attr in ('encoding', 'defaults', 'fallback', 'error_template', 'timestamp', 'rules',
                             'instance_warp', 'instance_entry_warp', 'instance_map_reference', 'unit_catalog', 'reference_names'):
                    if getattr(candidate, attr) != getattr(renderer.profile, attr):
                        raise ValueError('表示書式を再読込してください。')
            view = dict(filter=self.filter.text(), timestamps=self.display_timestamps.isChecked(),
                        unmapped=self.display_unmapped.isChecked(), tab=self.workspace_tabs.currentIndex(),
                        conversation=self.dialogue_panel.selection.currentIndex(),
                        merged=self.dialogue_panel.merge_checkbox.isChecked())
            expected_catalogs=self.loaded_catalog_hashes()
            catalogs={key:CATALOG_PATHS[key] for key in expected_catalogs}
            common = dict(recv=profiles['RECV'], send=profiles['SEND'], dialogue=DEFAULT_DIALOGUE_PROFILE)
            if self.multiple:
                save_multiple_project(destination, common, self.replay_report['sources'], view, self.project_note,
                                      catalogs=catalogs,expected_catalog_hashes=expected_catalogs)
            else:
                save_project(destination, dict(common, log=self.source_path, definitions=self.path.text()),
                             view, self.project_note, self.replay_report['source_sha256'],
                             catalogs=catalogs,expected_catalog_hashes=expected_catalogs)
            self.statusBar().showMessage('作業プロジェクトを保存しました。')
        except (OSError, ValueError):
            QMessageBox.critical(self, '作業を保存できません',
                                 '参照ファイルの変更・保存先・設定を確認してください。必要なら再読込してください。')

    def cancel_replay(self):
        self.cancelled = True
        self.worker.requestInterruption()
        self.apply_timer.stop()
        self.staged_events = []
        self.close()

    def _worker_finished(self):
        if self.closing or self.cancelled:
            self.close()

    def closeEvent(self, event):
        self.workspace_closing=True
        self.bridge.seal()
        self.history_tasks.cancel()
        self.closing = True
        self.apply_timer.stop()
        self.worker.requestInterruption()
        if self.worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)
        if event.isAccepted():
            if self in self.owner.offline_windows:
                self.owner.offline_windows.remove(self)
            self.deleteLater()
