"""Compact live summary and an optional inventory detail window."""
import json
from reconstruction.client_names import empty_client_names,item_name,map_label
from copy import deepcopy
from storage.observation_export import save_observations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QPushButton,
    QDialog, QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QTabWidget, QPlainTextEdit)


class PlayerPanel(QWidget):
    def __init__(self, store, on_source=None, source_sessions=None, *, names=None, navigation=None):
        super().__init__()
        self.store, self.revision = store, -1
        self.source_sessions = source_sessions if source_sessions is not None else {}
        self.on_source, self.catalog_rows = on_source, []
        self.names=names if names is not None else empty_client_names()
        self.navigation=navigation
        self.manual = False
        self.capture = -1
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        self.selection = QComboBox()
        self.selection.setMaximumWidth(155)
        self.selection.activated.connect(self.choose)
        layout.addWidget(self.selection)
        self.summary = QLabel('マップ: 不明  |  XY: 不明  |  所持品: 不明  |  Zeny: 不明')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary, 1)
        button = QPushButton('基本データ…')
        layout.addWidget(button)
        self.dialog = QDialog(self)
        self.dialog.setWindowTitle('基本データとキャラクター台帳')
        self.dialog.resize(900, 540)
        detail = QVBoxLayout(self.dialog)
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        detail.addWidget(self.detail_label)
        self.tabs = QTabWidget()
        detail.addWidget(self.tabs)
        self.items = QTableWidget(0, 5)
        self.items.setHorizontalHeaderLabels(['Index', 'ItemID', '個数', '品名（資料）', '鑑定'])
        self.items.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.items, '選択接続の所持品')
        catalog = QWidget()
        catalog_layout = QVBoxLayout(catalog)
        note = QLabel('キャラクター一覧と更新通知の直近観測値です。選択接続の現在状態とは分けて保持します。\n'
                      '名前・経験値・Zenyのセルを選ぶと、その値の根拠パケットへ移動できます。')
        note.setWordWrap(True)
        catalog_layout.addWidget(note)
        self.characters = QTableWidget(0, 7)
        self.characters.setHorizontalHeaderLabels(['Account', 'Slot', 'Character ID', '名前', 'BaseExp', 'Zeny', 'JobExp'])
        for column, width in enumerate((90, 45, 100, 150, 150, 110, 150)):
            self.characters.setColumnWidth(column, width)
        self.characters.setSelectionBehavior(QTableWidget.SelectRows)
        self.characters.setSelectionMode(QTableWidget.SingleSelection)
        self.characters.setEditTriggers(QTableWidget.NoEditTriggers)
        self.characters.itemSelectionChanged.connect(self.show_character)
        catalog_layout.addWidget(self.characters)
        self.character_detail = QPlainTextEdit()
        self.character_detail.setReadOnly(True)
        self.character_detail.setMaximumHeight(150)
        catalog_layout.addWidget(self.character_detail)
        self.character_source = QPushButton('選択した値の根拠パケット')
        self.character_source.setEnabled(on_source is not None)
        self.character_source.clicked.connect(self.jump_character)
        catalog_layout.addWidget(self.character_source)
        self.tabs.addTab(catalog, 'キャラクター台帳')
        save = QPushButton('基本データJSON保存…')
        save.clicked.connect(self.save)
        detail.addWidget(save)
        button.clicked.connect(self.show_inventory)

    def choose(self, *args):
        self.manual = True
        self.show_selected()

    def show_inventory(self):
        self.show_selected()
        from gui.layout import show_panel
        show_panel(self.dialog)

    def refresh(self):
        if self.revision == self.store.revision:
            return
        if self.capture != self.store.current_capture:
            self.manual = False
            self.capture = self.store.current_capture
        selected = self.selection.currentData()
        self.selection.clear()
        for key in self.store.states:
            self.selection.addItem(f'接続 {key[1]}', key)
        index = self.selection.findData(selected) if self.manual else self.selection.count() - 1
        self.selection.setCurrentIndex(max(0, index))
        self.selection.setVisible(self.selection.count() > 1)
        self.revision = self.store.revision
        self.refresh_characters()
        self.show_selected()

    @staticmethod
    def character_key(row):
        return (row['account_id'], row['character_id'],
                row['evidence']['character_list']['flow_id'] if row['account_id'] is None else None)

    def refresh_characters(self):
        index = self.characters.currentRow()
        selected = self.character_key(self.catalog_rows[index]) if 0 <= index < len(self.catalog_rows) else None
        column = max(0, self.characters.currentColumn())
        self.catalog_rows = deepcopy(list(self.store.characters.values()))
        blocked = self.characters.blockSignals(True)
        self.characters.setRowCount(len(self.catalog_rows))
        target = -1
        for index, row in enumerate(self.catalog_rows):
            for col, field in enumerate(('account_id', 'slot', 'character_id', 'character_name', 'base_exp', 'zeny', 'job_exp')):
                value = row.get(field)
                text = '不明' if value is None else f'{value:,}' if col >= 4 else str(value)
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, self.character_key(row))
                self.characters.setItem(index, col, item)
            if self.character_key(row) == selected:
                target = index
        self.characters.clearSelection()
        self.characters.setCurrentCell(target, column)
        self.characters.blockSignals(blocked)
        self.show_character()

    def show_character(self):
        index = self.characters.currentRow()
        row = self.catalog_rows[index] if 0 <= index < len(self.catalog_rows) else None
        self.character_detail.setPlainText(json.dumps(row, ensure_ascii=False, indent=2) if row else '')
        self.character_source.setEnabled(self.on_source is not None and row is not None)

    def jump_character(self):
        index = self.characters.currentRow()
        if self.on_source is None or not 0 <= index < len(self.catalog_rows):
            return
        row = self.catalog_rows[index]
        field = {3: 'character_name', 4: 'base_exp', 5: 'zeny', 6: 'job_exp'}.get(self.characters.currentColumn())
        reference = row['evidence'].get(field, row['evidence']['character_list'])
        if type(reference.get('packet_index')) is int and reference['packet_index'] >= 0:
            self.on_source(reference['packet_index'])

    def show_selected(self):
        state = self.store.states.get(self.selection.currentData())
        if state is None:
            self.summary.setText('マップ: 不明  |  XY: 不明  |  所持品: 不明  |  Zeny: 不明')
            self.items.setRowCount(0)
            self.detail_label.setText('基本データ未取得')
            return
        xy = f'({state.x}, {state.y})' if state.x is not None and state.y is not None else '不明'
        if state.destination_x is not None:
            xy += f' → ({state.destination_x}, {state.destination_y}) 到着未確認'
        quality = '全件受信' if state.inventory_complete else '更新中' if state.inventory_loading else '部分観測'
        inventory = (f'{len(state.items)}枠 / 合計{state.total_amount:,}個（{quality}）'
                     if state.items or state.inventory_complete or state.inventory_loading else '不明')
        zeny = f'{state.zeny:,}' if state.zeny is not None else '不明'
        if state.zeny_delta is not None:
            zeny += f'（前回比 {state.zeny_delta:+,}）'
        label=map_label(self.names,state.map_name,self.navigation)
        map_text=(state.map_name or '不明')+(f'（{label}）' if label else '')
        self.summary.setText(f'マップ: {map_text}  |  XY: {xy}  |  所持品: {inventory}  |  Zeny: {zeny}')
        self.detail_label.setText(f'{quality}。枠数はIndex数、合計個数はスタック数量の合計。'
                                 f'\n取得世代 {state.capture_session} / 接続 {state.flow_id} / 解析問題 {self.store.issue_count}件'
                                 f'\nキャラクター: {state.character_name or "不明"} / ID: {state.character_id}'
                                 f'\nBaseExp: {state.base_exp if state.base_exp is not None else "不明"}'
                                 f' / JobExp: {state.job_exp if state.job_exp is not None else "不明"}')
        self.items.setRowCount(len(state.items))
        for row, (index, item) in enumerate(sorted(state.items.items())):
            for column, value in enumerate((index, item['item_id'], item['amount'],item_name(self.names,item['item_id']),
                                               '鑑定済' if item.get('identified') is True else '未鑑定' if item.get('identified') is False else '不明')):
                self.items.setItem(row, column, QTableWidgetItem(str(value)))
            self.items.item(row,3).setToolTip('品名は識別済名称の資料です。観測した鑑定・識別状態は右欄に表示します。\n辞書SHA-256: '+str(self.names['_sha256'] or '未読込'))

    def save(self):
        report = dict(deepcopy(self.store.snapshot()),
                      source_sessions={str(k): v for k, v in self.source_sessions.items()})
        protected = list(self.source_sessions.values())
        definitions = getattr(self.window(), 'path', None)
        if definitions is not None:
            protected.append(definitions.text())
        path, _ = QFileDialog.getSaveFileName(self, '基本データを保存', 'player-observations.json', 'JSON (*.json)')
        if path:
            try:
                save_observations(path, report, protected)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, '保存できません', str(exc))
