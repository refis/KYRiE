"""Normal-shop observations and evidence, without automatic DB-ID conversion."""
import json
from reconstruction.client_names import empty_client_names,item_name
from copy import deepcopy

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QPlainTextEdit, QFileDialog, QMessageBox,
                               QMenu, QDialog, QFormLayout, QLineEdit, QCheckBox, QDialogButtonBox)
from gui.qt_messages import warning as warn
from gui.report_export import export_busy, export_report
from reconstruction.shop_export import ShopRenderer
from storage.observation_export import save_observation_text
from reconstruction.npc_initial_state import visibility_state

ASSOCIATION_LABELS = {'selector_and_buy_reply': '対象選択と購入応答を確認',
                      'after_close_list': 'close直後の一覧（callshop候補）',
                      'selector_only': '対象選択のみ', 'unresolved': '対象未解決'}


class ShopExportDialog(QDialog):
    def __init__(self, record, conversation, parent=None, *, names=None, identity=None):
        super().__init__(parent)
        self.record, self.conversation, self.result_text = deepcopy(record), deepcopy(conversation), None
        self.names = names if names is not None else empty_client_names()
        self.identity = dict(identity or {})
        self.setWindowTitle('通常ショップのAuriga編集用候補')
        self.resize(650, 250)
        form = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItem('会話なし: shop NPC定義', 'shop')
        self.mode.addItem('会話あり: 通常NPC + callshop + 別shop定義', 'callshop')
        if conversation and any(row['kind'] not in ('open', 'dismiss') for row in conversation.steps):
            self.mode.setCurrentIndex(1)
        form.addRow('生成形式', self.mode)
        self.npc_info = QLabel()
        self.npc_info.setWordWrap(True)
        form.addRow('配置元', self.npc_info)
        self.map_name = QLineEdit()
        self.map_name.setPlaceholderText('未観測の場合、確認したマップ名を入力')
        form.addRow('マップ', self.map_name)
        self.confirm_ids = QCheckBox('表示アイテムIDが出力先DBと一致することを確認済み')
        form.addRow(self.confirm_ids)
        form.addRow(QLabel('基本価格を使用します。元のNPC種・隠れたショップ名・条件式を確定する出力ではありません。'
                           '品名は識別済資料の併記のみで、宣言の数値IDは変えません。'))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('候補を生成')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.generate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.mode.currentIndexChanged.connect(self.refresh_placement)
        self.refresh_placement()

    def refresh_placement(self):
        npc = (self.conversation.npc if self.mode.currentData() == 'callshop' and self.conversation else self.record['npc'])
        self.map_name.setText(npc.get('map_name') or '')
        self.map_name.setReadOnly(bool(npc.get('map_name')))
        self.npc_info.setText(f'{npc.get("name") or "未解決"} / XY={npc.get("x")},{npc.get("y")} / 外見={npc.get("class_id")}'
                             f' / 初回状態={visibility_state(npc)}')

    def generate(self):
        try:
            self.result_text = ShopRenderer(client_names=self.names, identity=self.identity).render(
                self.record, self.mode.currentData(),
                item_ids_confirmed=self.confirm_ids.isChecked(), map_name=self.map_name.text().strip() or None,
                conversation=self.conversation)
            self.accept()
        except (ValueError, OSError) as exc:
            warn(self, 'ショップ候補を生成できません', str(exc))


class ShopPanel(QWidget):
    def __init__(self, store, show_source, sources, *, names=None):
        super().__init__()
        self.store, self.show_source, self.sources = store, show_source, sources
        self.names=names if names is not None else empty_client_names()
        self.revision = -1
        layout = QVBoxLayout(self)
        self.caption = QLabel('通常ショップの観測。クライアント表示IDをサーバーDBのIDとは断定しません。')
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        bar = QHBoxLayout()
        self.selection = QComboBox()
        self.selection.currentIndexChanged.connect(self.refresh_selected)
        bar.addWidget(self.selection, 1)
        for title, callback in [('根拠パケット', self.jump), ('ショップJSON保存…', self.save)]:
            button = QPushButton(title)
            if title == 'ショップJSON保存…':
                button.setText('保存…')
                menu = QMenu(button)
                menu.addAction('ショップ観測JSON…', callback)
                menu.addAction('Aurigaショップ候補…', self.export_candidate)
                button.setMenu(menu)
            else:
                button.clicked.connect(callback)
            bar.addWidget(button)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['表示アイテムID', '基本価格', '割引価格', '種類', '外見値', '装備位置値', '品名（資料）'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        layout.addWidget(self.evidence)

    def refresh(self):
        if self.revision == self.store.revision:
            return
        selected = self.selection.currentIndex()
        self.selection.blockSignals(True)
        self.selection.clear()
        for record in self.store.records:
            name = record['npc'].get('name') or (f'対象ID {record["actor_id"]}' if record['actor_id'] is not None else '対象不明')
            self.selection.addItem(f'{record["id"]}: {name} / {len(record["items"])}商品 / '
                                   f'{ASSOCIATION_LABELS[record["association"]]}')
        self.selection.setCurrentIndex(min(max(0, selected), len(self.store.records) - 1))
        self.selection.blockSignals(False)
        self.caption.setText(f'通常ショップ {len(self.store.records)}件 / 解析問題 {self.store.issue_count}件。'
                             '表示ID・価格の観測値です。サーバーDBのIDやNPC起因は未確定。')
        self.revision = self.store.revision
        self.refresh_selected()

    def refresh_selected(self):
        index = self.selection.currentIndex()
        record = self.store.records[index] if 0 <= index < len(self.store.records) else None
        self.table.setRowCount(len(record['items']) if record else 0)
        if record:
            for row, item in enumerate(record['items']):
                for col, key in enumerate(('client_item_id', 'price', 'discount_price', 'item_type', 'view_sprite', 'location')):
                    self.table.setItem(row, col, QTableWidgetItem(str(item.get(key, '未通知'))))
                label=QTableWidgetItem(item_name(self.names,item['client_item_id']))
                label.setToolTip('クライアント表示IDに対する名称資料です。サーバーDBのID一致を確定しません。\n辞書SHA-256: '+str(self.names['_sha256'] or '未読込'))
                self.table.setItem(row,6,label)
        self.evidence.setPlainText(json.dumps(record, ensure_ascii=False, indent=2) if record else '')

    def jump(self):
        index = self.selection.currentIndex()
        if 0 <= index < len(self.store.records):
            self.show_source(self.store.records[index]['packet']['packet_index'])

    def export_protected_paths(self):
        paths = list(self.sources.values())
        definitions = getattr(self.window(), 'path', None)
        if definitions is not None:
            paths.append(definitions.text())
        return paths

    def save(self):
        if export_busy(self):
            return
        # Freeze before the file dialog so later packets cannot change the payload.
        result = dict(deepcopy(self.store.snapshot()),
                      source_sessions={str(key): value for key, value in self.sources.items()})
        protected = self.export_protected_paths()
        path, _ = QFileDialog.getSaveFileName(self, 'ショップ観測を保存', 'shops.json', 'JSON (*.json)')
        if path:
            try:
                export_report(self, path, result, protected, label='ショップ観測')
            except (OSError, ValueError) as exc:
                warn(self, 'ショップ観測を保存できません', str(exc))

    def export_candidate(self):
        index = self.selection.currentIndex()
        if not 0 <= index < len(self.store.records):
            return
        record = self.store.records[index]
        conversation = next((item for item in self.store.dialogues.sessions
            if item.capture_session == record['capture_session'] and item.id == record.get('conversation_id')), None) if self.store.dialogues else None
        from reconstruction.identity_protection import identity_from_store
        players = getattr(self.window(), 'players', None)
        dialog = ShopExportDialog(record, conversation, self, names=self.names,
                                  identity=identity_from_store(players))
        protected = self.export_protected_paths()
        if dialog.exec() != QDialog.Accepted:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Aurigaショップ編集用候補を保存', 'shop-candidate.txt', 'Auriga script (*.txt)')
        if not path:
            return
        try:
            save_observation_text(path, dialog.result_text, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'ショップ候補を保存できません', str(exc))
