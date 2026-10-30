"""Bounded individual comparison over existing combat summaries; no new inference."""
from collections import Counter
from copy import deepcopy
import json
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                               QTableWidget,QTableWidgetItem,QAbstractItemView,QPlainTextEdit)
from reconstruction.actor_identity import actor_sort_key

DISPLAY_LIMIT = 1000


def source_identity(summary,world):
    key = tuple(summary['entity_key'])
    entity = world.entities.get(key)
    return dict(server_endpoint=deepcopy(entity.server_endpoint) if entity else None,
                capture_session=key[0],connection=key[1],map_generation=key[2],actor_id=key[3],appearance=key[4])


def range_text(stats):
    return '未取得' if not stats['count'] else str(stats['min'])+'～'+str(stats['max'])


class PerformanceIndividualPanel(QWidget):
    def __init__(self,on_source,parent=None):
        super().__init__(parent)
        self.on_source,self.rows = on_source,[]
        layout = QVBoxLayout(self)
        self.caption = QLabel('クラスまたは個体を選択してください。')
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        self.table = QTableWidget(0,10)
        self.table.setHorizontalHeaderLabels(['サーバー','取得/MAP世代/ActorID/視界区間','与通知','被通知',
            '速度通知','最大HP通知','与HP範囲','被HP範囲','最短HP tick差ms','要確認レコード'])
        self.table.setColumnWidth(0,155)
        self.table.setColumnWidth(1,190)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.first,self.last = QPushButton('個体の最初の根拠'),QPushButton('個体の最後の根拠')
        for button,endpoint in ((self.first,'first_packet_index'),(self.last,'last_packet_index')):
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False,key=endpoint:self.jump(key))
            actions.addWidget(button)
        layout.addLayout(actions)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def selected_key(self):
        row = self.selected()
        return (tuple(row['entity_key']),row['class_id']) if row else None

    def select_key(self,key):
        for index,row in enumerate(self.rows):
            if (tuple(row['entity_key']),row['class_id']) == key:
                self.table.selectRow(index)
                return True
        return False

    def set_summaries(self,summaries,world,observations):
        selected = self.selected_key()
        quality = {}
        for record in observations:
            key = (tuple(record['entity_key']),record['class_id'])
            count,flags = quality.setdefault(key,[0,Counter()])
            quality[key][0] += bool(record['flags'])
            flags.update(record['flags'])
        ordered = sorted(summaries,key=lambda row:actor_sort_key(source_identity(row,world)))
        self.rows = []
        for summary in ordered[:DISPLAY_LIMIT]:
            key = (tuple(summary['entity_key']),summary['class_id'])
            count,flags = quality.get(key,[0,Counter()])
            evidence = summary['evidence']
            self.rows.append(dict(entity_key=list(key[0]),class_id=key[1],identity=source_identity(summary,world),
                counts=deepcopy(summary['counts']),speeds=list(summary['speeds']),max_hp=list(summary['observed_max_hp']),
                outgoing_hp=deepcopy(summary['damage']['outgoing']['hp_damage_total']),
                incoming_hp=deepcopy(summary['damage']['incoming']['hp_damage_total']),
                min_hp_tick_ms=summary['outgoing_tick_interval']['min'],
                quality_records=count,quality_flags=dict(flags),evidence_count=len(evidence),
                first_packet_index=evidence[0] if evidence else None,last_packet_index=evidence[-1] if evidence else None))
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for index,row in enumerate(self.rows):
            identity=row['identity'];server=identity['server_endpoint'];key=row['entity_key']
            values = [str(server['ip'])+':'+str(server['port']) if server else '未取得',
                f'{key[0]}/{key[2]}/{key[3]}/{key[4]}',row['counts'].get('outgoing',0),row['counts'].get('incoming',0),
                ','.join(map(str,row['speeds'])) or '未取得',','.join(map(str,row['max_hp'])) or '未取得',
                range_text(row['outgoing_hp']),range_text(row['incoming_hp']),
                '未取得' if row['min_hp_tick_ms'] is None else row['min_hp_tick_ms'],row['quality_records']]
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setToolTip(str(value)+'\n'+identity['connection'])
                self.table.setItem(index,column,item)
        self.caption.setText(f'個体別の視界区間 {len(ordered)}件 / 表示 {len(self.rows)}件（最大{DISPLAY_LIMIT}件）。'
            '個体間・取得間の間隔を合算せず、設定ATK/DEF・個体数・ディレイは推測しません。')
        if self.rows and not self.select_key(selected):
            self.table.selectRow(0)
        self.show_selected()

    def show_selected(self):
        row = self.selected()
        self.detail.setPlainText(json.dumps(row,ensure_ascii=False,indent=2) if row else '')
        for button,key in ((self.first,'first_packet_index'),(self.last,'last_packet_index')):
            value=row.get(key) if row else None
            button.setEnabled(type(value) is int and value>=0)

    def jump(self,endpoint):
        row=self.selected();value=row.get(endpoint) if row else None
        if type(value) is int and value>=0:self.on_source(value)
