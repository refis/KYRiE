"""MOB skill summaries and packet evidence, sharing the existing MOB workspace."""
from gui.report_export import export_report,export_busy,prepare_mob_export,export_prepared
import json
from copy import deepcopy
from pathlib import Path
from storage.observation_export import save_observations, save_observation_text
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QPlainTextEdit, QSplitter, QFileDialog, QMessageBox, QMenu, QTabWidget)
from reconstruction.skills import load_skill_names_with_hash
from reconstruction.mob_skill_export import build_candidates, render_candidates, DEFAULT_PROFILE
from gui.cast_review import CastReviewPanel
from gui.skill_notifications import SkillNotificationPanel, DISPLAY_LIMIT
from gui.view_limits import IntervalPager, preview_document


class MobSkillPanel(QWidget):
    def __init__(self, store, on_source, source_sessions, combat=None):
        super().__init__()
        self.store, self.on_source, self.source_sessions = store, on_source, source_sessions
        self.combat = combat
        self.entity_key = None
        self.revision = -1
        self.rows = []
        self.names = {}
        self.names_sha256 = None
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItems(['クラス別（全観測）', '選択個体'])
        self.scope.currentIndexChanged.connect(self.rebuild)
        actions.addWidget(self.scope)
        self.count = QLabel('0 件')
        actions.addWidget(self.count, 1)
        for label, callback in [('名前辞書を再読込', self.reload_names), ('根拠パケット', self.jump), ('スキルJSON保存…', self.save)]:
            button = QPushButton(label)
            if label == 'スキルJSON保存…':
                button.setText('保存…')
                menu = QMenu(button)
                menu.addAction('全スキル観測JSON…', callback)
                menu.addAction('全観測のAuriga DB編集用候補…', self.save_candidates)
                menu.addAction('選択スキルの設定を編集…', self.edit_candidate)
                button.setMenu(menu)
            else:
                button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.note = QLabel('間隔は個体内の観測値です。設定ディレイ・使用確率・AI条件は未確定です。')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['クラス', 'SkillID', '名前', '詠唱開始', '攻撃通知', 'その他通知', '中断', 'Lv', '最短tick間隔 ms'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for column, width in enumerate((70, 70, 160, 80, 80, 90, 60, 90, 155)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.show_selected)
        splitter.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText('スキル行を選ぶと個体別の間隔・詠唱・レベル・対象と根拠JSONを確認できます。')
        detail_tabs = QTabWidget()
        detail_tabs.addTab(self.detail, '概要・根拠JSON')
        self.notifications = SkillNotificationPanel(lambda index: self.on_source(index))
        detail_tabs.addTab(self.notifications, '通知一覧')
        interval_page = QWidget()
        interval_layout = QVBoxLayout(interval_page)
        interval_layout.addWidget(QLabel('個体内の比較区間です。通知間隔を設定ディレイ・使用回数とは扱いません。'))
        self.interval_table = QTableWidget(0, 7)
        self.interval_table.setHorizontalHeaderLabels(['系列', '取得/個体/出現', '対象ID', '結果', '時間差 ms', '開始Packet', '終了Packet'])
        self.interval_table.setColumnWidth(0, 220)
        self.interval_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.interval_table.setSelectionMode(QTableWidget.SingleSelection)
        self.interval_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.interval_pager=IntervalPager()
        interval_layout.addWidget(self.interval_pager)
        self.interval_pager.changed.connect(self.render_intervals)
        interval_layout.addWidget(self.interval_table)
        interval_actions = QHBoxLayout()
        self.interval_start = QPushButton('比較開始の根拠')
        self.interval_end = QPushButton('比較終了の根拠')
        for button, field in ((self.interval_start, 'from_packet_index'), (self.interval_end, 'packet_index')):
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, endpoint=field: self.jump_interval(endpoint))
            interval_actions.addWidget(button)
        interval_layout.addLayout(interval_actions)
        self.interval_table.itemSelectionChanged.connect(self.interval_selection_changed)
        self.interval_table.cellDoubleClicked.connect(lambda *_: self.jump_interval('packet_index'))
        detail_tabs.addTab(interval_page, '間隔の根拠')
        self.cast_review = CastReviewPanel(lambda index: self.on_source(index))
        detail_tabs.addTab(self.cast_review, '詠唱の対応候補')
        splitter.addWidget(detail_tabs)
        splitter.setSizes([180, 130])
        layout.addWidget(splitter)
        self.reload_names()

    def set_entity(self, key):
        if key != self.entity_key:
            self.entity_key = key
            if self.scope.currentIndex() == 1:
                self.rebuild()

    def refresh(self):
        if self.revision != self.store.revision:
            self.rebuild()

    def reload_names(self):
        try:
            names, sha256 = load_skill_names_with_hash()
        except (OSError, ValueError) as exc:
            self.note.setText(f'名前辞書を読み込めません（前の辞書を保持）: {exc}')
            return
        self.names = names
        self.names_sha256 = sha256
        self.rebuild()

    def rebuild(self, *args):
        notification_key = self.notifications.selected_key()
        selected = self.table.currentRow()
        selected_key = ((self.rows[selected]['class_id'], self.rows[selected]['skill_id'])
                        if 0 <= selected < len(self.rows) else None)
        aggregate = self.scope.currentIndex() == 0
        self.rows = (self.store.summaries(aggregate=True) if aggregate else
                     self.store.summaries(entity_key=self.entity_key) if self.entity_key is not None else [])
        self.table.setRowCount(0)
        for row, item in enumerate(self.rows):
            self.table.insertRow(row)
            counts = item['counts']
            interval = item['intervals']['server_tick_damage']['min_ms']
            levels = ','.join(map(str, item['known_levels'])) or '不明'
            if item['unknown_level_notifications'] and item['known_levels']:
                levels += ' / 不明あり'
            values = [item['class_id'], item['skill_id'], self.names.get(item['skill_id'], '未登録'),
                      counts.get('cast', 0), counts.get('damage', 0), counts.get('effect', 0) + counts.get('ground', 0),
                      counts.get('cancel', 0), levels, interval]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem('未取得' if value is None else str(value)))
        self.revision = self.store.revision
        self.count.setText(f'{len(self.rows)} 件 / 通知 {len(self.store.events)} 件')
        self.note.setText('間隔は個体内の観測値。設定ディレイ・使用確率・AI条件は未確定。'
                          f' 解析問題 {self.store.issue_count}件 / 分類不可通知 {self.store.unattributed}件'
                          + (' / 保存上限に到達' if self.store.saturated else ''))
        self.detail.clear()
        self.notifications.set_observations([])
        if selected_key:
            for row, item in enumerate(self.rows):
                if (item['class_id'], item['skill_id']) == selected_key:
                    self.table.selectRow(row)
                    self.notifications.select_key(notification_key)
                    break

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def show_selected(self):
        self.notifications.set_observations([])
        self.cast_review.set_observations([])
        self.interval_pager.clear()
        self.interval_table.setRowCount(0)
        self.interval_start.setEnabled(False)
        self.interval_end.setEnabled(False)
        item = self.selected()
        if item is None:
            self.detail.clear()
            return
        indices = set(item['evidence'])
        records = [event for event in self.store.events if event['packet_index'] in indices
                   and event['class_id'] == item['class_id'] and event['skill_id'] == item['skill_id']
                   and (item['entity_key'] is None or tuple(event['entity_key']) == tuple(item['entity_key']))]
        self.notifications.set_observations(records,self.combat.events if self.combat else [],
            self.store.world.display_observations, self.store.world.display_dropped == 0)
        self.cast_review.set_observations(records)
        def value(number):
            return '未観測' if number is None else str(number)
        lines = [f'クラス {item["class_id"]} / {self.names.get(item["skill_id"], "名称未登録")} ({item["skill_id"]})',
                 f'観測個体（出現記録）: {item["source_appearances"]} / レベル: '
                 + (','.join(map(str, item['known_levels'])) or '不明')
                 + f' / 不明レベル通知 {item["unknown_level_notifications"]}件',
                 '詠唱通知の時間 ms: ' + (','.join(map(str, item['cast_ms'])) or '未観測')]
        for basis, label in [('capture_cast_start', '詠唱開始の取得時刻差'),
                             ('server_tick_damage', 'ダメージ通知tick差'), ('server_tick_ground', '地点通知tick差'),
                             ('capture_effect_notification', '効果通知の取得時刻差（同じ対象・結果）')]:
            interval = item['intervals'][basis]
            lines.append(f'{label}: 最短 {value(interval["min_ms"])} ms / 比較 {interval["count"]}件')
        lines.append(f'根拠JSONの通知本文表示は末尾{DISPLAY_LIMIT}通知まで。全件はスキルJSON保存で確認できます。')
        lines.append('すべて個体内で算出。設定ディレイ・使用回数・AI条件は確定していません。')
        lines.append('効果通知は重複・継続効果を含む可能性があり、取得時刻差をスキル使用間隔と断定しません。')
        self.detail.setPlainText('\n'.join(lines) + '\n\n根拠JSON:\n' +
                                 json.dumps(preview_document(item,records),ensure_ascii=False,indent=2))
        samples=[(basis,sample) for basis,series in item['intervals'].items() for sample in series['samples']]
        self.interval_pager.set_rows(samples,(item['class_id'],item['skill_id'],str(item['entity_key'])))

    def render_intervals(self):
        self.interval_table.setRowCount(0)
        self.interval_start.setEnabled(False);self.interval_end.setEnabled(False)
        samples=self.interval_pager.visible()
        self.interval_table.setRowCount(len(samples))
        labels={'capture_cast_start':'詠唱開始の取得時刻差','server_tick_damage':'ダメージ通知tick差',
                'server_tick_ground':'地点通知tick差','capture_effect_notification':'効果通知の取得時刻差'}
        for row,(basis,sample) in enumerate(samples):
            key=sample['entity_key']
            values=[labels.get(basis,basis),f'{key[0]}/{key[3]}/{key[4]}',sample.get('target_id','—'),sample.get('result','—'),
                    sample['duration_ms'],sample['from_packet_index'],sample['packet_index']]
            for column,value in enumerate(values):
                cell=QTableWidgetItem(str(value));cell.setData(Qt.UserRole,dict(sample,basis=basis))
                cell.setToolTip(json.dumps(sample,ensure_ascii=False));self.interval_table.setItem(row,column,cell)

    def interval_selection_changed(self):
        row = self.interval_table.currentRow()
        cell = self.interval_table.item(row, 0) if row >= 0 else None
        sample = cell.data(Qt.UserRole) if cell else {}
        for button, field in ((self.interval_start, 'from_packet_index'), (self.interval_end, 'packet_index')):
            index = sample.get(field)
            button.setEnabled(type(index) is int and index >= 0)

    def jump_interval(self, endpoint):
        row = self.interval_table.currentRow()
        cell = self.interval_table.item(row, 0) if row >= 0 else None
        if cell:
            index = cell.data(Qt.UserRole).get(endpoint)
            if type(index) is int and index >= 0:
                self.on_source(index)

    def jump(self):
        item = self.selected()
        if item and item['evidence']:
            self.on_source(item['evidence'][-1])

    def save(self):
        if export_busy(self):return
        prepared=prepare_mob_export(self,self.store,self.source_sessions,self.names)
        report = None if prepared is not None else dict(deepcopy(self.store.snapshot()), source_sessions={str(k): v for k, v in self.source_sessions.items()},
                      skill_names={str(k): v for k, v in self.names.items()})
        protected = self.export_protected_paths()
        path, _ = QFileDialog.getSaveFileName(self, 'MOBスキル観測を保存', 'mob-skills.json', 'JSON (*.json)')
        if path:
            try:
                if prepared is not None:export_prepared(self,path,prepared,protected,label="MOBスキル観測")
                else:export_report(self,path,report,protected,label="MOBスキル観測")
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, '保存できません', str(exc))

    def edit_candidate(self):
        selected = self.selected()
        if selected is None:
            QMessageBox.information(self, 'スキルを選択', '編集するスキル行を選択してください。')
            return
        report = build_candidates(self.store.snapshot(), self.names, self.source_sessions)
        candidate = next((item for item in report['candidates']
                          if (item['class_id'], item['skill_id']) ==
                          (selected['class_id'], selected['skill_id'])), None)
        if candidate is not None:
            from gui.mob_skill_editor import MobSkillEditor
            dialog = MobSkillEditor(candidate, self.source_sessions, self)
            dialog.exec()
            dialog.deleteLater()

    def export_protected_paths(self):
        paths = [*self.source_sessions.values(), DEFAULT_PROFILE]
        definitions = getattr(self.window(), 'path', None)
        if definitions is not None:
            paths.append(definitions.text())
        return paths

    def save_candidates(self):
        try:
            report = deepcopy(build_candidates(self.store.snapshot(), self.names, self.source_sessions))
            text = render_candidates(report)
            protected = self.export_protected_paths()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '候補を保存できません', str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, 'MOBスキルの編集用候補を保存',
                                            'mob-skill-review.txt', 'Commented DB (*.txt);;JSON (*.json)')
        if not path:
            return
        try:
            if Path(path).suffix.lower() == '.json':
                save_observations(path, report, protected)
            else:
                save_observation_text(path, text, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '候補を保存できません', str(exc))
