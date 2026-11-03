"""Explicit trial adoption and manual label times, isolated from observed data."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from storage.observation_export import validate_export_destination
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QLineEdit, QCheckBox, QPushButton, QPlainTextEdit, QFileDialog, QMessageBox)
from reconstruction.event_timer_export import (build_timer_candidate, DEFAULT_PROFILE, load_timer_candidate,
                                                render_timer_text, MAX_CONFIGURED_BYTES, validate_timer_trial)
from gui.event_trials import timer_event_label
from gui.qt_messages import warning as warn


class EventTimerEditor(QDialog):
    def __init__(self, report, trial_index, parent=None, is_current=None):
        if is_current is not None and not is_current():
            raise ValueError('観測または比較条件が更新されています。閉じて再比較してください。')
        trial = validate_timer_trial(report, trial_index)
        super().__init__(parent)
        self.report, self.trial_index = deepcopy(report), trial_index
        self.is_current = is_current
        self.setWindowTitle('NPCタイマー候補の手動採用')
        self.resize(820, 750)
        layout = QVBoxLayout(self)
        variant = next((item for item in report['variants'] if trial_index in item['trial_indices']), None)
        count = variant['count'] if variant else 0
        target = report['npc_identity']
        note = QLabel(f'対象: {target["name"]} / {target["map_name"]} / 採用試行 {trial_index + 1}\n'
                      f'同じ観測列 {count}試行 / 観測列 {len(report["variants"])}種類。反復不足・相違の可能性も確認してください。\n'
                      '全時刻を手入力してください。観測時間は自動代入しません。\n'
                      '時刻は1〜2147483647ms、同値は同じOnTimerラベルにまとめます。\n'
                      '対象NPC本文へ統合する候補です。開始・再開・ループ条件や元の設定は復元しません。')
        note.setWordWrap(True)
        note.setTextFormat(Qt.PlainText)
        layout.addWidget(note)
        self.table = QTableWidget(len(trial['events']), 4)
        self.table.setHorizontalHeaderLabels(['演出', 'Packet', '観測基準からms', '手入力OnTimer ms'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 180)
        self.times = []
        for index, event in enumerate(trial['events']):
            row = event['observation']
            label = timer_event_label(row)
            for col, value in enumerate((label, row['packet_index'], event['offset_ms'])):
                self.table.setItem(index, col, QTableWidgetItem(str(value)))
            field = QLineEdit()
            field.setMaxLength(10)
            field.textChanged.connect(self.invalidate_confirmation)
            self.times.append(field)
            self.table.setCellWidget(index, 3, field)
        layout.addWidget(self.table)
        self.confirmed = QCheckBox('対象NPC・採用試行・全手入力時刻と、未観測や他ユーザー混入の可能性を確認した')
        self.confirmed.toggled.connect(self.clear_preview)
        layout.addWidget(self.confirmed)
        load_button = QPushButton('同じ比較根拠の設定JSONを読み込む…')
        load_button.clicked.connect(self.load)
        layout.addWidget(load_button)
        actions = QHBoxLayout()
        for label, callback in [('候補を表示', self.generate), ('設定・候補・全比較根拠をJSON保存…', self.save)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        text_button = QPushButton('確認済み候補を根拠付きテキスト保存…')
        text_button.clicked.connect(lambda: self.save(as_text=True))
        layout.addWidget(text_button)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)

    def clear_preview(self, *args):
        self.preview.clear()

    def invalidate_confirmation(self, *args):
        self.confirmed.setChecked(False)
        self.clear_preview()

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, '同じNPC・比較根拠のタイマー設定を再編集', '', 'JSON (*.json)')
        if not path:
            return
        try:
            self.check_current()
            document = load_timer_candidate(path, self.report, self.trial_index)
            self.check_current()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'タイマー設定を読み込めません', str(exc))
            return
        for field, value in zip(self.times, document['manual_times_ms']):
            field.setText(str(value))
        self.confirmed.setChecked(False)
        self.clear_preview()

    def check_current(self):
        if self.is_current is not None and not self.is_current():
            raise ValueError('観測または比較条件が更新されています。閉じて再比較してください。')

    def document(self):
        self.check_current()
        values = []
        for field in self.times:
            if not re.fullmatch(r'[0-9]{1,10}', field.text()):
                raise ValueError('全時刻を整数で明示してください。')
            values.append(int(field.text()))
        return build_timer_candidate(self.report, self.trial_index, values, confirmed=self.confirmed.isChecked())

    def generate(self):
        try:
            self.preview.setPlainText(self.document()['auriga'])
        except (ValueError, OSError) as exc:
            self.preview.setPlainText(str(exc))
            warn(self, '候補を生成できません', str(exc))

    def save(self, checked=False, *, as_text=False):
        temporary = None
        try:
            document = self.document()
            text = (render_timer_text(document, self.report, self.trial_index) if as_text else
                    json.dumps(document, ensure_ascii=False, indent=2) + '\n')
            if len(text.encode('utf-8')) > MAX_CONFIGURED_BYTES:
                raise ValueError('候補の保存内容が32MiBを超えています。')
            path, _ = QFileDialog.getSaveFileName(self, '手動採用したタイマー候補を保存',
                                                'event-timer-candidate.txt' if as_text else 'event-timer-candidate.json',
                                                'Text (*.txt)' if as_text else 'JSON (*.json)')
            if not path:
                return
            self.check_current()
            destination = Path(path).resolve()
            protected = {Path(ref).resolve() for ref in self.report['source_sessions'].values() if ref}
            protected.add(DEFAULT_PROFILE.resolve())
            if destination in protected:
                raise ValueError('元ログ・生成書式へ上書きできません。')
            validate_export_destination(destination, protected)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                             delete=False, suffix='.tmp') as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, destination)
            self.preview.setPlainText(document['auriga'])
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '候補を保存できません', str(exc))
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
