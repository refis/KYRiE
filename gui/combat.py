"""Observed MOB performance, with raw evidence and no base-stat reconstruction."""
from gui.report_export import export_report,export_busy,prepare_mob_export,export_prepared
import json
from copy import deepcopy
from gui.performance_individuals import PerformanceIndividualPanel
from gui.view_limits import IntervalPager, preview_document
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QPlainTextEdit, QSplitter, QFileDialog, QMessageBox, QTabWidget)


def display_range(stats):
    return '未取得' if not stats['count'] else f'{stats["min"]}～{stats["max"]}'


class MobPerformancePanel(QWidget):
    def __init__(self, store, on_source, source_sessions):
        super().__init__()
        self.store, self.on_source, self.source_sessions = store, on_source, source_sessions
        self.entity_key, self.revision, self.rows = None, -1, []
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItems(['クラス別（全観測）', '選択個体'])
        self.scope.currentIndexChanged.connect(self.rebuild)
        actions.addWidget(self.scope)
        self.count = QLabel('0 件')
        actions.addWidget(self.count, 1)
        source = QPushButton('根拠パケット')
        source.clicked.connect(self.jump)
        actions.addWidget(source)
        save = QPushButton('性能観測JSON保存…')
        save.clicked.connect(self.save)
        actions.addWidget(save)
        layout.addLayout(actions)
        self.note = QLabel('ダメージは対象・条件に依存する通知値です。元のATK／DEF・設定ディレイは未確定です。')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['クラス', '与ダメ通知', '被ダメ通知', '速度通知値',
            '最大HP通知値', '与HPダメ範囲', '被HPダメ範囲', '最短HP tick間隔 ms'])
        for column, width in enumerate((70, 90, 90, 120, 130, 130, 130, 155)):
            self.table.setColumnWidth(column, width)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText('行を選択すると動作ディレイ、HP通知、対象別の値と根拠を確認できます。')
        detail_tabs = QTabWidget()
        detail_tabs.addTab(self.detail, '概要・根拠JSON')
        self.individuals=PerformanceIndividualPanel(lambda index:self.on_source(index))
        detail_tabs.addTab(self.individuals,'個体別比較')
        interval_page = QWidget()
        interval_layout = QVBoxLayout(interval_page)
        interval_layout.addWidget(QLabel('同じ個体・相手・表示種別・HP/SP系列の通知間隔です。設定攻撃ディレイではありません。'))
        self.interval_table = QTableWidget(0, 8)
        self.interval_table.setHorizontalHeaderLabels(['系列', '取得/個体/出現', '相手ID', '相手クラス',
                                                       '表示種別', '時間差 ms', '開始Packet', '終了Packet'])
        self.interval_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.interval_table.setSelectionMode(QTableWidget.SingleSelection)
        self.interval_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.interval_pager=IntervalPager()
        interval_layout.addWidget(self.interval_pager)
        self.interval_pager.changed.connect(self.render_intervals)
        interval_layout.addWidget(self.interval_table)
        actions = QHBoxLayout()
        self.interval_start, self.interval_end = QPushButton('比較開始の根拠'), QPushButton('比較終了の根拠')
        for button, field in ((self.interval_start, 'from_packet_index'), (self.interval_end, 'packet_index')):
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, endpoint=field: self.jump_interval(endpoint))
            actions.addWidget(button)
        interval_layout.addLayout(actions)
        self.interval_table.itemSelectionChanged.connect(self.interval_selection_changed)
        self.interval_table.cellDoubleClicked.connect(lambda *_: self.jump_interval('packet_index'))
        detail_tabs.addTab(interval_page, '攻撃間隔の根拠')
        split.addWidget(detail_tabs)
        split.setSizes([180, 130])
        layout.addWidget(split)

    def set_entity(self, key):
        if self.entity_key != key:
            self.entity_key = key
            if self.scope.currentIndex() == 1:
                self.rebuild()

    def refresh(self):
        if self.revision != self.store.revision:
            self.rebuild()

    def rebuild(self, *args):
        individual_key=self.individuals.selected_key()
        self.clear_intervals()
        current = self.selected()
        selected_class = current['class_id'] if current else None
        self.rows = (self.store.summaries(aggregate=True) if self.scope.currentIndex() == 0 else
                     self.store.summaries(self.entity_key) if self.entity_key is not None else [])
        self.table.setRowCount(0)
        for row, item in enumerate(self.rows):
            self.table.insertRow(row)
            values = [item['class_id'], item['counts'].get('outgoing', 0), item['counts'].get('incoming', 0),
                      ','.join(map(str, item['speeds'])) or '未取得',
                      ','.join(map(str, item['observed_max_hp'])) or '未取得',
                      display_range(item['damage']['outgoing']['hp_damage_total']),
                      display_range(item['damage']['incoming']['hp_damage_total']),
                      item['outgoing_tick_interval']['min']]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem('未取得' if value is None else str(value)))
        self.revision = self.store.revision
        self.count.setText(f'{len(self.rows)} 件 / 観測 {len(self.store.events)} 件 / 解析問題 {self.store.issue_count}件'
                           + (' / 保存上限' if self.store.saturated else ''))
        self.detail.clear()
        self.individuals.set_summaries([],self.store.world,[])
        if selected_class is not None:
            for row, item in enumerate(self.rows):
                if item['class_id'] == selected_class:
                    self.table.selectRow(row)
                    self.individuals.select_key(individual_key)
                    break

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def show_selected(self):
        self.clear_intervals()
        self.individuals.set_summaries([],self.store.world,[])
        item = self.selected()
        if item is None:
            self.detail.clear()
            return
        indices = set(item['evidence'])
        records = [record for record in self.store.events if record['packet_index'] in indices
                   and record['class_id'] == item['class_id']
                   and (item['entity_key'] is None or record['entity_key'] == item['entity_key'])]
        summaries = ([row for row in self.store.summaries() if row['class_id']==item['class_id']]
                     if item['entity_key'] is None else [item])
        self.individuals.set_summaries(summaries,self.store.world,records)
        lines = [f'クラス {item["class_id"]} / 観測個体（出現記録） {item["source_appearances"]}',
                 '与ダメージは対象や耐性等を含む通知結果です。元のATK／DEFは算出していません。',
                 'MOBが送信元の動作ディレイ通知値: ' + display_range(item['damage']['outgoing']['source_delay']),
                 'MOBが対象の動作ディレイ通知値: ' + display_range(item['damage']['incoming']['target_delay']),
                 '画面JSONは長い一覧を末尾1000件へ制限し、省略数を表示します。全記録は性能観測JSON保存で確認できます。',
                 '間隔は同一個体・対象・表示タイプ・HP/SP系列内で計算。左右の通知値を合計し、分割数では乗算しません。']
        self.detail.setPlainText('\n'.join(lines) + '\n\n根拠JSON:\n' +
                                 json.dumps(preview_document(item,records),ensure_ascii=False,indent=2))
        samples=[(label,sample) for field,label in (('outgoing_tick_interval','与HP'),('outgoing_sp_tick_interval','与SP'))
                 for sample in item[field]['samples']]
        self.interval_pager.set_rows(samples,(item['class_id'],str(item['entity_key'])))

    def render_intervals(self):
        self.interval_table.setRowCount(0)
        self.interval_start.setEnabled(False);self.interval_end.setEnabled(False)
        samples=self.interval_pager.visible();self.interval_table.setRowCount(len(samples))
        for row,(label,sample) in enumerate(samples):
            key=sample['entity_key']
            values=[label,f'{key[0]}/{key[3]}/{key[4]}',sample['counterparty_id'],sample.get('counterparty_class_id'),
                    sample['action'],sample['duration_ms'],sample['from_packet_index'],sample['packet_index']]
            for column,value in enumerate(values):
                cell=QTableWidgetItem('未観測' if value is None else str(value));cell.setData(Qt.UserRole,sample)
                cell.setToolTip(json.dumps(sample,ensure_ascii=False));self.interval_table.setItem(row,column,cell)

    def clear_intervals(self):
        self.interval_pager.clear()
        self.interval_table.setRowCount(0)
        self.interval_start.setEnabled(False)
        self.interval_end.setEnabled(False)

    def interval_selection_changed(self):
        row = self.interval_table.currentRow()
        cell = self.interval_table.item(row, 0) if row >= 0 else None
        sample = cell.data(Qt.UserRole) if cell else {}
        for button, field in ((self.interval_start, 'from_packet_index'), (self.interval_end, 'packet_index')):
            value = sample.get(field)
            button.setEnabled(type(value) is int and value >= 0)

    def jump_interval(self, endpoint):
        row = self.interval_table.currentRow()
        cell = self.interval_table.item(row, 0) if row >= 0 else None
        if cell:
            value = cell.data(Qt.UserRole).get(endpoint)
            if type(value) is int and value >= 0:
                self.on_source(value)

    def jump(self):
        item = self.selected()
        if item and item['evidence']:
            self.on_source(item['evidence'][-1])

    def save(self):
        if export_busy(self):return
        prepared=prepare_mob_export(self,self.store,self.source_sessions)
        report = None if prepared is not None else dict(deepcopy(self.store.snapshot()), source_sessions={str(k): v for k, v in self.source_sessions.items()})
        protected = list(self.source_sessions.values())
        definitions = getattr(self.window(), 'path', None)
        if definitions is not None:
            protected.append(definitions.text())
        path, _ = QFileDialog.getSaveFileName(self, 'MOB性能観測を保存', 'mob-performance.json', 'JSON (*.json)')
        if path:
            try:
                if prepared is not None:export_prepared(self,path,prepared,protected,label="MOB性能観測")
                else:export_report(self,path,report,protected,label="MOB性能観測")
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, '保存できません', str(exc))
