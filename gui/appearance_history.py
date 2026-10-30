"""Bounded, read-only navigation of observed NPC/MOB appearance changes."""
from copy import deepcopy
from datetime import datetime
import json
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                               QTableWidget,QTableWidgetItem,QAbstractItemView,QPlainTextEdit)

LABELS = {'class_id':'class','name':'名前','x':'X','y':'Y','direction':'向き',
          'destination_x':'移動先X','destination_y':'移動先Y','speed':'速度','options':'オプション',
          'sex':'性別','hair_style':'髪型','hair_color':'髪色','cloth_color':'服色',
          'head_top':'頭上段','head_mid':'頭中段','head_bottom':'頭下段','robe':'衣装','style':'style'}


def change_text(changes):
    parts = []
    def value(item):
        return '未取得' if item is None else json.dumps(item,ensure_ascii=False)
    for field,pair in changes.items():
        before,after = pair.get('before'),pair.get('after')
        if field == 'appearance_data' and isinstance(after,dict):
            before = before if isinstance(before,dict) else {}
            for key in sorted(set(before)|set(after)):
                if before.get(key) != after.get(key):
                    parts.append(LABELS.get(key,key)+': '+value(before.get(key))+' → '+value(after.get(key)))
        else:
            parts.append(LABELS.get(field,field)+': '+value(before)+' → '+value(after))
    return ' / '.join(parts)


class AppearanceHistoryPanel(QWidget):
    def __init__(self,on_source,parent=None):
        super().__init__(parent)
        self.on_source = on_source
        self.rows,self.entity_key = [],None
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.caption = QLabel('個体を選択すると、保持中の変更を表示します。')
        self.caption.setWordWrap(True)
        actions.addWidget(self.caption)
        self.source_button = QPushButton('変更の根拠パケット')
        self.source_button.setEnabled(False)
        self.source_button.clicked.connect(self.jump)
        actions.addWidget(self.source_button)
        layout.addLayout(actions)
        self.table = QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['時刻','Packet','変更箇所','観測状況'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnWidth(2,350)
        self.table.setColumnWidth(3,230)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def selected_key(self):
        row = self.selected()
        return (row['capture_session'],row['packet_index']) if row else None

    def select_key(self,key):
        for index,row in enumerate(self.rows):
            if (row['capture_session'],row['packet_index']) == key:
                self.table.selectRow(index)
                return True
        return False

    def set_entity(self,entity):
        selected = self.selected_key() if entity and entity.key == self.entity_key else None
        self.entity_key = entity.key if entity else None
        self.rows = deepcopy(entity.display_changes[-32:]) if entity else []
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for index,row in enumerate(self.rows):
            try:
                time = datetime.fromtimestamp(row['timestamp']).strftime('%H:%M:%S.%f')[:-3]
            except (ValueError,TypeError,OverflowError,OSError):
                time = '時刻不正'
            situation = '視界内で観測' if row['in_sight'] else '視界外／再出現時に判明（変更時点は未観測）'
            values = [time,row['packet_index'],change_text(row['changes']),situation]
            for column,value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(index,column,item)
        self.caption.setText(f'{entity.kind} ID {entity.actor_id} / 保持中の変更 {len(self.rows)}件。'
            '選択した視界観測区間で保持できた変更の直近32件まで。全履歴・変更原因の確定ではありません。' if entity else
            '個体を選択すると、保持中の変更を表示します。')
        if self.rows and not self.select_key(selected):
            self.table.selectRow(len(self.rows)-1)
        self.show_selected()

    def show_selected(self):
        row = self.selected()
        self.detail.setPlainText(json.dumps(row,ensure_ascii=False,indent=2) if row else '')
        self.source_button.setEnabled(bool(row and type(row.get('packet_index')) is int and row['packet_index'] >= 0))

    def jump(self):
        row = self.selected()
        if row and type(row.get('packet_index')) is int and row['packet_index'] >= 0:
            self.on_source(row['packet_index'])
