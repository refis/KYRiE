"""Visibility/reobservation report, separate from server monster configuration."""
import json
from copy import deepcopy
from storage.observation_export import save_observations, save_observation_text
from pathlib import Path
from reconstruction.mob_spawn_export import build_candidates, render_candidates, DEFAULT_PROFILE
from gui.report_export import export_report, export_busy, prepare_mob_export, export_prepared
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QPlainTextEdit, QFileDialog, QMessageBox)


class MobSpawnPanel(QWidget):
    def __init__(self, store, on_source, sources):
        super().__init__()
        self.store, self.on_source, self.sources = store, on_source, sources
        self.revision, self.rows = -1, []
        layout = QVBoxLayout(self)
        note = QLabel('追跡数・同じActorIDの再観測です。設定上の湧き数・再出現時間や視界再進入との区別は未確定。')
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.count = QLabel()
        actions.addWidget(self.count, 1)
        for title, callback in [('根拠パケット', self.jump), ('配置観測JSON保存…', self.save),
                                ('配置編集用候補…', self.save_candidates)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        edit = QPushButton('選択した配置候補の設定を編集…')
        edit.clicked.connect(self.edit_candidate)
        layout.addWidget(edit)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['取得/マップ世代', 'マップ', 'クラス', '出現記録', '追跡数ピーク', '死亡通知', '同ID再観測'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

    def refresh(self):
        if self.revision == self.store.revision:
            return
        self.revision = self.store.revision
        report = self.store.snapshot()
        self.rows = report['groups']
        self.table.setRowCount(len(self.rows))
        for row, item in enumerate(self.rows):
            for col, value in enumerate((f'{item["capture_session"]}/{item["map_generation"]}', item['map_name'] or '未観測', item['class_id'],
                    item['appearances'], item['peak_tracked'], item['deaths'], item['observed_reappearances'])):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.count.setText(f'{len(self.rows)}接続・マップ世代別集計 / World解析問題 {report["world_issue_count"]}件 / 上限到達 {report["saturated"]}')
        self.show_selected()

    def show_selected(self):
        row = self.table.currentRow()
        self.detail.setPlainText(json.dumps(self.rows[row], ensure_ascii=False, indent=2) if 0 <= row < len(self.rows) else '')

    def jump(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.rows) and self.rows[row]['first_positions']:
            self.on_source(self.rows[row]['first_positions'][0]['packet_index'])

    def save(self):
        if export_busy(self):
            return
        prepared = prepare_mob_export(self, self.store, self.sources)
        report = (None if prepared is not None else
                  dict(deepcopy(self.store.snapshot()),
                       source_sessions={str(key): value for key, value in self.sources.items()}))
        protected = self.export_protected_paths()
        path, _ = QFileDialog.getSaveFileName(self, 'MOB配置観測を保存', 'mob-spawns.json', 'JSON (*.json)')
        if path:
            try:
                if prepared is not None:
                    export_prepared(self, path, prepared, protected, label='MOB配置観測')
                else:
                    export_report(self, path, report, protected, label='MOB配置観測')
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, '保存できません', str(exc))

    def edit_candidate(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.rows):
            QMessageBox.information(self, '配置を選択', '編集する配置観測行を選択してください。')
            return
        selected = self.rows[row]
        report = build_candidates(self.store.snapshot(), self.sources)
        keys = ('capture_session', 'connection', 'map_generation')
        candidate = next((item for item in report['candidates']
                          if item['scope'] == {key: selected[key] for key in keys}
                          and item['placement_fields']['class_id'] == selected['class_id']), None)
        if candidate is not None:
            from gui.mob_spawn_editor import MobSpawnEditor
            dialog = MobSpawnEditor(candidate, self.sources, self)
            dialog.exec()
            dialog.deleteLater()

    def export_protected_paths(self):
        paths = [*self.sources.values(), DEFAULT_PROFILE]
        definitions = getattr(self.window(), 'path', None)
        if definitions is not None:
            paths.append(definitions.text())
        return paths

    def save_candidates(self):
        try:
            report = deepcopy(build_candidates(self.store.snapshot(), self.sources))
            text = render_candidates(report)
            protected = self.export_protected_paths()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '候補を保存できません', str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, '全観測のMOB配置候補を保存',
                                            'mob-spawn-review.txt', 'Commented placement (*.txt);;JSON (*.json)')
        if not path:
            return
        try:
            if Path(path).suffix.lower() == '.json':
                save_observations(path, report, protected)
            else:
                save_observation_text(path, text, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '候補を保存できません', str(exc))
