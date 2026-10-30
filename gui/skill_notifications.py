"""Read-only bounded inspection of already retained MOB skill notifications."""
from copy import deepcopy
import json
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                               QTableWidget,QTableWidgetItem,QAbstractItemView,QPlainTextEdit,QComboBox,QSpinBox)

from reconstruction.skill_hp_context import skill_hp_contexts, compare_percentage

DISPLAY_LIMIT = 1000
FLAGS = {'invalid_time':'時刻不正','timestamp_reversed':'時刻逆行','assumed_boundary':'途中取得',
         'tick_reversed_or_ambiguous':'tick逆行・未確定','previous_observation_unreliable':'前通知は要確認'}
KINDS = {'cast':'詠唱開始','damage':'攻撃通知','effect':'効果通知','ground':'地点通知','cancel':'取消通知'}


def record_key(row):
    return (row['capture_session'],row['packet_index'],tuple(row['entity_key']),row['skill_id'])


def level_text(row):
    if 'level_raw' not in row:
        return '未通知'
    return str(row['level']) if row.get('level') is not None else '不明 (raw '+str(row['level_raw'])+')'


def target_text(row):
    if row['kind'] == 'ground':
        return f'地点 {row.get("x")},{row.get("y")}'
    target = row.get('target_id')
    if not target:
        return '対象未取得'
    label = {'self':'自分','observed_mob':'観測MOB','other':'他対象（未分類）'}.get(row.get('target_kind'),'対象')
    return label+' ID '+str(target)


def values_text(row):
    fields = {'cast':('cast_ms',),'damage':('damage','divisions','hit','server_tick','source_delay','target_delay'),
              'effect':('effect_value','result'),'ground':('server_tick',),'cancel':('linked_cast_index',)}
    return ' / '.join(key+'='+str(row[key]) for key in fields[row['kind']] if key in row)


class SkillNotificationPanel(QWidget):
    def __init__(self,on_source,parent=None):
        super().__init__(parent)
        self.on_source,self.rows = on_source,[]
        self.hp_contexts = []
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.caption = QLabel('スキルを選択すると、保持中の通知を表示します。')
        self.caption.setWordWrap(True)
        actions.addWidget(self.caption)
        self.source_button = QPushButton('通知の根拠パケット')
        self.source_button.setEnabled(False)
        self.source_button.clicked.connect(self.jump)
        actions.addWidget(self.source_button)
        self.hp_source = QPushButton('割合通知の根拠')
        self.hp_source.setEnabled(False)
        self.hp_source.clicked.connect(self.jump_hp)
        actions.addWidget(self.hp_source)
        layout.addLayout(actions)
        hp_actions = QHBoxLayout()
        self.hp_relation = QComboBox()
        for label,value in (('割合を比較しない','none'),('通知値が以下','le'),('通知値が以上','ge')):
            self.hp_relation.addItem(label,value)
        self.hp_threshold = QSpinBox()
        self.hp_threshold.setRange(0,100)
        self.hp_threshold.setValue(50)
        self.hp_threshold.setSuffix('%')
        hp_actions.addWidget(self.hp_relation)
        hp_actions.addWidget(self.hp_threshold)
        hp_actions.addWidget(QLabel('5%刻みの直前通知との比較です。現在HP・スキル条件は未確定。'))
        layout.addLayout(hp_actions)
        self.hp_relation.currentIndexChanged.connect(self.update_hp_comparison)
        self.hp_threshold.valueChanged.connect(self.update_hp_comparison)
        self.table = QTableWidget(0,10)
        self.table.setHorizontalHeaderLabels(['Packet','取得/MAP世代/ActorID/視界区間','通知','対象','Lv','観測値','品質','直前HP割合（5%刻み）','取得差ms','通知値の比較'])
        self.table.setColumnWidth(1,170)
        self.table.setColumnWidth(3,180)
        self.table.setColumnWidth(5,270)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
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
        return record_key(row) if row else None

    def select_key(self,key):
        for index,row in enumerate(self.rows):
            if record_key(row) == key:
                self.table.selectRow(index)
                return True
        return False

    def set_observations(self,observations,hp_observations=(),changes=(),history_complete=True):
        selected = self.selected_key()
        self.rows = deepcopy(observations[-DISPLAY_LIMIT:])
        self.hp_contexts = skill_hp_contexts(self.rows,hp_observations,changes,history_complete)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for index,row in enumerate(self.rows):
            key = row['entity_key']
            identity = f'{row["capture_session"]}/{key[2]}/{row["actor_id"]}/{key[4]}'
            values = [row['packet_index'],identity,KINDS[row['kind']],target_text(row),level_text(row),
                      values_text(row),' / '.join(FLAGS.get(flag,flag) for flag in row['flags']) or '報告フラグなし（完全性は未確認）']
            context=self.hp_contexts[index]
            percent=(str(context['hp_percent'])+'%' if context['status'] in ('observed','quality_warning') else '未取得／要確認')
            if context['status']=='quality_warning':percent+='（要確認）'
            if context['status']=='class_changed':percent='class変更後は未取得'
            values.extend([percent,'未判定' if context['age_ms'] is None else context['age_ms'],'—'])
            for column,value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value)+'\n'+str(row['connection']))
                self.table.setItem(index,column,item)
        self.caption.setText(f'保持中 {len(observations)}通知 / 表示は末尾 {len(self.rows)}件（最大{DISPLAY_LIMIT}件）。'
            '通知数は使用回数ではありません。全記録はスキルJSON保存から確認できます。')
        if self.rows and not self.select_key(selected):
            self.table.selectRow(len(self.rows)-1)
        self.update_hp_comparison()
        self.show_selected()

    def update_hp_comparison(self,*args):
        for index,context in enumerate(self.hp_contexts):
            result=compare_percentage(context,self.hp_threshold.value(),self.hp_relation.currentData())
            text = ('—' if self.hp_relation.currentData()=='none' else '未判定' if result is None
                    else '通知値では該当' if result else '通知値では非該当')
            self.table.setItem(index,9,QTableWidgetItem(text))

    def show_selected(self):
        row = self.selected()
        index=self.table.currentRow()
        context=self.hp_contexts[index] if row else None
        self.detail.setPlainText(json.dumps(dict(skill=row,hp_percentage_reference=context),ensure_ascii=False,indent=2) if row else '')
        self.hp_source.setEnabled(bool(context and type(context['packet_index']) is int and context['packet_index']>=0))
        self.source_button.setEnabled(bool(row and type(row.get('packet_index')) is int and row['packet_index'] >= 0))

    def jump(self):
        row = self.selected()
        if row and type(row.get('packet_index')) is int and row['packet_index'] >= 0:
            self.on_source(row['packet_index'])

    def jump_hp(self):
        index=self.table.currentRow()
        if 0 <= index < len(self.hp_contexts):
            packet=self.hp_contexts[index]['packet_index']
            if type(packet) is int and packet>=0:self.on_source(packet)
