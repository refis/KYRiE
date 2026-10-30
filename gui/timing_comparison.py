"""Explicit comparison of observed dialogue intervals, never timer code generation."""
import json
from pathlib import Path
from storage.observation_export import save_observation_text
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox)
from reconstruction.timing import build_timeline, summarize_timings, npc_identity

STATUS = {'insufficient_repeats': '比較不足', 'repeated_consistent': '反復一致・設定値は未確定',
          'repeated_variable': '変動あり'}


class TimingComparisonPanel(QWidget):
    def __init__(self, store, on_source):
        super().__init__()
        self.store, self.on_source = store, on_source
        self.item, self.report, self.key, self.groups = None, None, None, []
        layout = QVBoxLayout(self)
        self.note = QLabel('同じNPCの同じ観測経路を比較します。取得時間差はサーバーのタイマー設定値ではありません。')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        actions = QHBoxLayout()
        for label, callback in [('選択NPCの反復を比較', self.compute), ('比較JSON保存…', self.save),
                                ('区間開始の根拠', lambda: self.jump('from_packet_index')),
                                ('区間末尾の根拠', lambda: self.jump('to_packet_index'))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['経路', '観測数', '最小ms', '中央値ms', '最大ms', '幅ms', '比較結果'])
        self.table.setColumnWidth(6, 220)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_samples)
        layout.addWidget(self.table)
        self.samples = QTableWidget(0, 6)
        self.samples.setHorizontalHeaderLabels(['出典', '取得世代', '会話', '実測ms', '開始Packet', '末尾Packet'])
        self.samples.setSelectionBehavior(QTableWidget.SelectRows)
        self.samples.setSelectionMode(QTableWidget.SingleSelection)
        self.samples.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.samples)

    def current_key(self):
        identity = npc_identity(self.item) if self.item else None
        return json.dumps(identity, sort_keys=True), self.store.revision

    def set_conversation(self, item):
        self.item = item
        if self.key != self.current_key():
            self.report, self.groups = None, []
            self.table.setRowCount(0)
            self.samples.setRowCount(0)
            self.note.setText('選択NPCの観測を比較してください。入力待ちは除外し、タイマー設定値は確定しません。')

    def compute(self):
        identity = npc_identity(self.item) if self.item else None
        if identity is None:
            self.note.setText('比較にはマップ・名前・外見・XYが判明したNPCを選択してください。')
            return
        try:
            conversations = [item for item in self.store.sessions if npc_identity(item) == identity]
            if sum(len(item.steps) + len(item.parallel_presentations) + len(item.resource_observations)
                   for item in conversations) > 100000:
                raise ValueError('比較対象が100000観測を超えています。')
            timelines = [build_timeline(item, self.store.source_refs.get(item.capture_session, ''))
                         for item in conversations]
            summary = summarize_timings(timelines)
            self.report = dict(schema_version=1, npc_identity=identity, timelines=timelines, summary=summary,
                               source_sessions=dict(self.store.source_refs), server_timer_confirmed=False,
                               transport_quality='not_verified')
            self.key = self.current_key()
            self.groups = summary['groups']
            self.table.setRowCount(len(self.groups))
            for index, group in enumerate(self.groups):
                values = [group['path_hash'][:10], group['count'], group['min_ms'], group['median_ms'],
                          group['max_ms'], group['spread_ms'], STATUS[group['status']]]
                for column, value in enumerate(values):
                    self.table.setItem(index, column, QTableWidgetItem(str(value)))
            self.samples.setRowCount(0)
            self.note.setText(f'{len(timelines)}会話 / 比較群 {len(self.groups)}件 / '
                f'品質による除外 {sum(len(row["excluded_gaps"]) for row in timelines)}区間 / '
                f'入力待ち {sum(wait["complete"] for row in timelines for wait in row["waits"])}件 / '
                f'未応答の待機 {sum(not wait["complete"] for row in timelines for wait in row["waits"])}件。'
                '3観測未満は比較不足。反復一致でもタイマー設定・起因は未確定、通信品質は未検証。')
            if self.groups:
                self.table.selectRow(0)
                self.show_samples()
        except ValueError as exc:
            self.report, self.groups = None, []
            self.table.setRowCount(0)
            self.samples.setRowCount(0)
            QMessageBox.warning(self, '比較できません', str(exc))

    def selected_group(self):
        row = self.table.currentRow()
        return self.groups[row] if 0 <= row < len(self.groups) else None

    def show_samples(self):
        group = self.selected_group()
        samples = group['samples'] if group else []
        self.samples.setRowCount(len(samples))
        for index, sample in enumerate(samples):
            source = Path(sample['source_ref']) if sample['source_ref'] else None
            source_label = (source.parent.name or source.name) if source else '取得中'
            values = [source_label, sample['capture_session'], sample['conversation_id'],
                      sample['duration_ms'], sample['from_packet_index'], sample['to_packet_index']]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setToolTip(sample['source_ref'])
                self.samples.setItem(index, column, item)
        if samples:
            self.samples.selectRow(0)

    def jump(self, endpoint):
        if self.key != self.current_key():
            self.set_conversation(self.item)
            return
        group, row = self.selected_group(), self.samples.currentRow()
        if group and 0 <= row < len(group['samples']):
            index = group['samples'][row][endpoint]
            if type(index) is int and index >= 0:
                self.on_source(index)

    def save(self):
        if self.report is None or self.key != self.current_key():
            QMessageBox.information(self, '比較が必要です', '現在の観測で反復を比較してから保存してください。')
            return
        try:
            text = json.dumps(self.report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
            if len(text.encode('utf-8')) > 32 * 1024 * 1024:
                raise ValueError('比較JSONが32MiBを超えています。')
            protected = list(self.store.source_refs.values())
            definitions = getattr(self.window(), 'path', None)
            if definitions is not None:
                protected.append(definitions.text())
            path, _ = QFileDialog.getSaveFileName(self, '反復比較を保存', 'dialogue-timing-comparison.json', 'JSON (*.json)')
            if path:
                save_observation_text(path, text, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '比較を保存できません', str(exc))
