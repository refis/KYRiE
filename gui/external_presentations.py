"""External candidate review; optional explicit adoption never confirms the caller."""
from reconstruction.speech_origin import index_player_notifications
from reconstruction.player_notification_review import review_player_notification_repeats
from reconstruction.dialogue import DialogueStore
from copy import deepcopy
import json
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton, QPlainTextEdit, QMessageBox)

KINDS = {'emotion': 'エモーション', 'effect': 'エフェクト', 'sound': '効果音',
         'effect_remove': 'エフェクト解除',
         'effect_value': '値付きエフェクト',
         'event_marker': 'イベントアイコン',
         'overhead': '頭上メッセージ', 'unittalk': 'ユニット発言'}


class ExternalPresentationPanel(QWidget):
    def __init__(self, on_source, store=None, on_changed=None):
        super().__init__()
        self.on_source, self.rows = on_source, []
        self.store, self.on_changed = store, on_changed
        self.conversation = None
        self.is_current = None
        self.player_review = None
        layout = QVBoxLayout(self)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        layout.addWidget(QLabel(
            '外部演出の命令採用（emotion／effect／解除／overhead／unittalk）。'
            '呼出し元は未確定のまま。未確認行はコメントのみ。sound等は採用不可。'))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ['採用', '取得 / 会話', '演出', '受信対象 / ID / 観測区間', '演出Packet', '直前会話Packet'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnWidth(0, 50)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.itemChanged.connect(self.toggle_adoption)
        self.table.cellDoubleClicked.connect(lambda row, column: self.jump('packet_index') if column != 0 else None)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.event_button = QPushButton('演出の根拠パケット')
        self.anchor_button = QPushButton('直前会話の根拠パケット')
        self.event_button.clicked.connect(lambda: self.jump('packet_index'))
        self.anchor_button.clicked.connect(lambda: self.jump('anchor_packet_index'))
        actions.addWidget(self.event_button)
        actions.addWidget(self.anchor_button)
        layout.addLayout(actions)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)
        self.set_conversation(None)

    def set_conversation(self, conversation, group=None, sources=None, player_notifications=(), *, is_current=None):
        self.rows = []
        self.conversation = conversation
        self.is_current = is_current
        sources = sources or {}
        contributions = group['contributions'] if group else ([dict(conversation=vars(conversation),
            source_ref=sources.get(conversation.capture_session,sources.get(str(conversation.capture_session),'')))] if conversation else [])
        notifications=index_player_notifications(player_notifications)
        seen=set();duplicates=0;source_mismatches=0
        for contribution in contributions:
            item=contribution['conversation']
            current=sources.get(item['capture_session'],sources.get(str(item['capture_session']),''))
            source=contribution.get('source_ref','')
            if source and current and source!=current:
                source_mismatches+=1
                continue
            source=source or current
            records=list(item.get('external_presentations',[]))
            records+=notifications.get((item['capture_session'],item['flow_id'],item['id'],item['actor_id']),[])
            for record in records:
                index=record.get('after_step_index');steps=item.get('steps',[])
                anchor=steps[index].get('packet_index') if type(index) is int and 0<=index<len(steps) else None
                if type(anchor) is not int or anchor<0 or type(record.get('packet_index')) is not int or anchor>=record['packet_index']:
                    anchor=None
                row=deepcopy(dict(record,source_ref=source,anchor_packet_index=anchor))
                signature=json.dumps(row,sort_keys=True,ensure_ascii=True)
                if signature in seen:
                    duplicates+=1
                    continue
                seen.add(signature);self.rows.append(row)
        self.rows.sort(key=lambda row:(row['capture_session'],row['packet_index']))
        try:
            self.player_review=review_player_notification_repeats(contributions,player_notifications,sources)
            self.player_review_error=''
        except ValueError as exc:
            self.player_review=None;self.player_review_error=str(exc)
        with QSignalBlocker(self.table):
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.table.setRowCount(len(self.rows))
            for number, row in enumerate(self.rows):
                context={'during_dialogue':'会話中','input_wait':'入力待ち中','close_wait':'close応答待ち中'}.get(row['context'],'') if row.get('entity_kind')=='PLAYER' else ''
                adoptable = (row.get('context') == 'external_candidate' and row.get('entity_kind') == 'NPC'
                             and row.get('kind') in DialogueStore.ADOPTABLE_EXTERNAL_KINDS
                             and bool((row.get('npc') or {}).get('name'))
                             and self.store is not None and self.conversation is not None
                             and not group)
                check = QTableWidgetItem()
                if adoptable:
                    check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    check.setCheckState(Qt.Checked if row.get('adoption_confirmed') else Qt.Unchecked)
                    check.setData(Qt.UserRole, row['packet_index'])
                else:
                    check.setFlags(Qt.ItemIsSelectable)
                    if row.get('entity_kind') == 'PLAYER':
                        check.setToolTip('本人宛て通知は外部NPC命令採用の対象外です。')
                    elif row.get('kind') not in DialogueStore.ADOPTABLE_EXTERNAL_KINDS:
                        check.setToolTip('この種別は命令採用できません。')
                    elif group:
                        check.setToolTip('統合表示では採用を切り替えません。単一会話を選んでください。')
                    else:
                        check.setToolTip('名称不明など、命令化できない候補です。')
                values = [f'{row["capture_session"]} / {row["conversation_id"]}',
                          KINDS.get(row['kind'], row['kind'])+(' / '+context if context else ''),
                          f'{row["npc"].get("name") or ('本人プレイヤー' if row.get('entity_kind')=='PLAYER' else '名称不明')} / {row["actor_id"]} / {row["npc"].get("appearance", "不明")}',
                          row['packet_index'], row['anchor_packet_index']]
                self.table.setItem(number, 0, check)
                for column, value in enumerate(values):
                    cell = QTableWidgetItem('—' if value is None else str(value))
                    cell.setToolTip(row['source_ref'])
                    self.table.setItem(number, column + 1, cell)
        conflicts = group.get('presentation_check', {}).get('conflicts', 0) if group else 0
        players=sum(row.get('entity_kind')=='PLAYER' for row in self.rows)
        self.caption.setText(f'外部演出候補 {len(self.rows)-players}件 / 本人宛て関連通知 {players}件。受信対象と会話NPCは別に保持。'
            '呼出し元は未確定で、他ユーザー操作の混入可能性があります。'
            +f' 同一根拠の重複 {duplicates}件 / 出典不一致の寄与 {source_mismatches}件を表示対象外。'
            + (f' 同じ会話経路の演出不一致 {conflicts}経路（外部以外の演出も含む）。' if conflicts else ''))
        if self.player_review and self.player_review['groups']:
            counts={status:sum(group['status']==status for group in self.player_review['groups'])
                    for status in ('observed_match','observed_difference','insufficient_observations')}
            self.caption.setText(self.caption.text()+f'\n本人通知の同一経路比較: 内容一致 {counts["observed_match"]}経路 / 有無・本文・文脈の差分 {counts["observed_difference"]}経路 / 比較不足 {counts["insufficient_observations"]}経路。未観測を欠落や非発生と断定しません。')
        elif self.player_review_error:
            self.caption.setText(self.caption.text()+'\n本人通知の比較: '+self.player_review_error)
        if self.player_review and (self.player_review['excluded'] or self.player_review['duplicate_observations']):
            self.caption.setText(self.caption.text()+f'\n本人通知比較の対象外 {len(self.player_review["excluded"])}観測 / 重複 {self.player_review["duplicate_observations"]}観測（理由は根拠JSON）。')
        self.show_selected()

    def toggle_adoption(self, cell):
        if cell is None or cell.column() != 0 or self.store is None or self.conversation is None:
            return
        packet_index = cell.data(Qt.UserRole)
        if packet_index is None:
            return
        try:
            self.store.set_external_adoption(self.conversation, packet_index, cell.checkState() == Qt.Checked)
        except ValueError as exc:
            with QSignalBlocker(self.table):
                cell.setCheckState(Qt.Unchecked)
            QMessageBox.warning(self, '命令採用を変更できません', str(exc))
            return
        if self.on_changed:
            self.on_changed()

    def check_current(self):
        if self.is_current is not None and not self.is_current():
            self.rows=[]
            self.conversation=None
            self.player_review=None
            with QSignalBlocker(self.table):
                self.table.setRowCount(0)
            self.detail.clear()
            self.event_button.setEnabled(False);self.anchor_button.setEnabled(False)
            self.caption.setText('観測または出典が更新されています。会話一覧を更新して選択し直してください。')
            return False
        return True

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def show_selected(self):
        if not self.check_current():return
        row = self.selected()
        evidence=deepcopy(row) if row else {}
        if self.player_review and (self.player_review['groups'] or self.player_review['excluded']):
            evidence['player_notification_repeat_review']=self.player_review
        text=json.dumps(evidence,ensure_ascii=False,indent=2) if evidence else ''
        if len(text)>200000:
            text=text[:200000]+'\n… 表示上限。全根拠は元の観測JSONに保持されています。'
        self.detail.setPlainText(text)
        for button, key in ((self.event_button, 'packet_index'), (self.anchor_button, 'anchor_packet_index')):
            value = row.get(key) if row else None
            button.setEnabled(type(value) is int and value >= 0)

    def jump(self, key):
        if not self.check_current():return
        row = self.selected()
        value = row.get(key) if row else None
        if type(value) is int and value >= 0:
            self.on_source(value)
