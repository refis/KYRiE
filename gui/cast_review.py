"""Navigate existing MOB cast candidates without inferring success or settings."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPushButton
from reconstruction.cast_review import build_cast_review
from gui.view_limits import IntervalPager


class CastReviewPanel(QWidget):
    def __init__(self, on_source):
        super().__init__()
        self.on_source = on_source
        layout = QVBoxLayout(self)
        note = QLabel('既存解析の対応候補です。通知までの時間差を実詠唱時間・成功・設定値とは断定しません。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['取得/個体/出現', '対象ID', '詠唱通知 ms', '後続まで ms',
                                             '観測状態', '後続通知', '開始Packet', '後続Packet', '追跡終了理由'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pager=IntervalPager(noun='候補',ordering='観測順')
        self.pager.changed.connect(self.render_rows)
        layout.addWidget(self.pager)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.start, self.end = QPushButton('詠唱開始の根拠'), QPushButton('後続通知の根拠')
        self.tracking = QPushButton('追跡終了の確認パケット')
        for button, field in ((self.start, 'from_packet_index'), (self.end, 'packet_index'),
                              (self.tracking, 'tracking_packet_index')):
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, endpoint=field: self.jump(endpoint))
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table.itemSelectionChanged.connect(self.selection_changed)

    def set_observations(self, observations):
        if not observations:
            self.pager.clear()
            return
        identity=tuple(sorted({(tuple(row['entity_key']),row['class_id'],row['skill_id']) for row in observations},key=str))
        self.pager.set_rows(build_cast_review(observations),identity)

    def render_rows(self):
        self.table.setRowCount(0)
        self.start.setEnabled(False)
        self.end.setEnabled(False)
        self.tracking.setEnabled(False)
        statuses = {'pending': '後続未観測', 'effect_observed': '効果通知との対応候補',
                    'cancelled': '取消通知との対応候補', 'superseded': '次の詠唱通知あり',
                    'interrupted': '追跡終了', 'capture_changed': '取得世代変更',
                    'decode_error': '解析停止', 'capacity_reached': '記録上限'}
        items=self.pager.visible()
        self.table.setRowCount(len(items))
        for row,item in enumerate(items):
            key = item['entity_key']
            tracking = item['tracking_end'] or {}
            item['tracking_packet_index'] = tracking.get('packet_index')
            reasons = {'removed': '消滅通知', 'dead': '死亡通知', 'previous_map': 'マップ移動',
                       'replaced': '別種別へ更新', 'entity_missing': '個体記録なし',
                       'class_changed': 'クラス変更', 'superseded': '次の詠唱通知',
                       'capture_changed': '取得世代変更', 'decode_error': '解析停止',
                       'capacity_reached': '記録上限'}
            values = [f'{key[0]}/{key[3]}/{key[4]}', item['target_id'], item['notified_cast_ms'], item['elapsed_ms'],
                      statuses.get(item['outcome'], item['outcome']) + (' / 要確認' if item['flags'] else ''),
                      {'cancel': '取消', 'effect': '効果', 'damage': 'ダメージ', 'ground': '地点'}.get(item['end_kind'], item['end_kind']),
                      item['from_packet_index'], item['packet_index'],
                      reasons.get(tracking.get('reason'), tracking.get('reason'))]
            for col, value in enumerate(values):
                cell = QTableWidgetItem('—' if value is None else str(value))
                cell.setData(Qt.UserRole, item)
                cell.setToolTip(json.dumps(item, ensure_ascii=False))
                self.table.setItem(row, col, cell)

    def selected(self):
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        return cell.data(Qt.UserRole) if cell else {}

    def selection_changed(self):
        item = self.selected()
        for button, key in ((self.start, 'from_packet_index'), (self.end, 'packet_index'),
                            (self.tracking, 'tracking_packet_index')):
            value = item.get(key)
            button.setEnabled(type(value) is int and value >= 0)

    def jump(self, key):
        value = self.selected().get(key)
        if type(value) is int and value >= 0:
            self.on_source(value)
