"""Server ActorID observation review; visibility intervals remain independent."""
from dataclasses import asdict
import json
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton, QPlainTextEdit)


class ActorHistoryPanel(QWidget):
    def __init__(self, on_source):
        super().__init__()
        self.on_source, self.rows = on_source, []
        layout = QVBoxLayout(self)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['名前 / クラス', 'MAP', 'MAP世代 / 観測区間', '状態', '保持中の先頭Packet', '最後のPacket'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.first_button = QPushButton('保持中の先頭根拠')
        self.last_button = QPushButton('最後の根拠')
        self.first_button.clicked.connect(lambda: self.jump(0))
        self.last_button.clicked.connect(lambda: self.jump(-1))
        actions.addWidget(self.first_button)
        actions.addWidget(self.last_button)
        layout.addLayout(actions)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)
        self.set_entity(None, [])

    def set_entity(self, selected, records):
        if selected is None:
            rows = []
        elif selected.server_endpoint is None:
            rows = [selected]
        else:
            rows = [item for item in records if item.capture_session == selected.capture_session
                    and item.server_endpoint == selected.server_endpoint and item.actor_id == selected.actor_id]
        self.rows = [asdict(item) for item in rows]
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(self.rows))
        for number, row in enumerate(self.rows):
            evidence = row['evidence']
            values = [f'{row["name"] or "名称不明"} / {row["class_id"]}', row['map_name'] or '未取得',
                      f'{row["map_generation"]} / {row["appearance"]}', row['state'],
                      evidence[0]['packet_index'] if evidence else None, evidence[-1]['packet_index'] if evidence else None]
            for column, value in enumerate(values):
                self.table.setItem(number, column, QTableWidgetItem('—' if value is None else str(value)))
        server = selected.server_endpoint if selected else None
        scope = f'{server["ip"]}:{server["port"]} / ActorID {selected.actor_id}' if server else 'サーバー未取得（選択区間のみ）'
        self.caption.setText(f'{scope} / {len(self.rows)}観測区間。表示中のみのフィルターには依存しません。'
                             '同一実体・連番割当・再出現設定は未確定。取得セッションを跨いで統合しません。')
        self.show_selected()

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def show_selected(self):
        row = self.selected()
        self.detail.setPlainText(json.dumps(row, ensure_ascii=False, indent=2) if row else '')
        enabled = bool(row and row['evidence'])
        self.first_button.setEnabled(enabled)
        self.last_button.setEnabled(enabled)

    def jump(self, endpoint):
        row = self.selected()
        if row and row['evidence']:
            value = row['evidence'][endpoint].get('packet_index')
            if type(value) is int and value >= 0:
                self.on_source(value)
