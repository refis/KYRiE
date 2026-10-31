"""Conversation evidence and editable-profile Auriga preview, separate from raw logs."""
from reconstruction.client_names import empty_client_names,quest_reference,item_name
import json
from copy import deepcopy
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
                               QPlainTextEdit, QSplitter, QLabel, QFileDialog, QMessageBox,
                               QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QCheckBox, QMenu)
from reconstruction.auriga import AurigaRenderer
from reconstruction.dialogue_review import build_review_queue
from reconstruction.timing import build_timeline
from reconstruction.touch import is_touch
from reconstruction.speech_origin import index_player_notifications
from reconstruction.branches import build_merged, observation_key
from gui.timing_comparison import TimingComparisonPanel
from gui.event_trials import EventTrialPanel
from gui.external_presentations import ExternalPresentationPanel
from gui.deferred_json import DeferredJsonView
from storage.observation_export import save_observations, save_observation_text

INTERVAL_LABELS = {'anchor': '基準', 'input_wait': '入力応答まで', 'during_input_wait': '入力待ち中',
                   'observation_only': '同一接続の変化・起因未確定',
                   'unanswered_termination': '未応答のまま終了',
                   'boundary': 'マップ移動', 'response_latency': '操作後の応答',
                   'autonomous_gap': '入力を挟まない間隔', 'ambiguous': '対応不明', 'invalid_time': '時刻不正'}
KIND_LABELS = {'dialogue_size':'会話サイズ', 'dialogue_position':'会話位置', 'dialogue_alignment':'会話整列', 'npc_display_action': 'NPC外見変更', 'script_command': '受信命令候補', 'visibility_action': 'NPC表示状態変更', 'status_action': '状態異常通知', 'progress_action': '会話中プログレスバー', 'open': '会話開始', 'mes': '台詞', 'emotion': 'エモーション', 'effect': 'エフェクト', 'sound': '効果音',
               'announcement': 'アナウンス（会話中の関連観測）',
               'unittalk': 'ユニット発言',
               'effect_remove': 'エフェクト解除',
               'effect_value': '値付きエフェクト',
               'late_continue': '終了後のnext応答候補', 'late_choice': '終了後の選択応答候補',
               'late_number_reply': '終了後の数値応答候補', 'late_text_reply': '終了後の文字応答候補',
               'resource_zeny': 'Zeny観測', 'resource_item_gain': '所持品増加', 'resource_item_loss': '所持品減少',
               'resource_quest_add': 'クエスト追加観測', 'resource_quest_delete': 'クエスト削除観測',
               'resource_quest_state': 'クエスト状態観測',
               'resource_quest_count': 'クエスト目標数観測',
               'next': '次へ待機', 'continue': '次へ操作',
               'menu': '選択肢', 'choice': '選択操作', 'number': '数値入力待機', 'text': '文字入力待機',
               'number_reply': '数値入力', 'text_reply': '文字入力', 'close': '終了待機',
               'dismiss': '終了操作', 'cutin': 'カットイン', 'clear': '会話消去', 'map_changed': 'マップ移動',
               'shop_opened': 'ショップ遷移', 'post_close_warp': 'close応答後のマップ移動',
               'classchange': '外見変更', 'progressbar': 'プログレスバー', 'viewpoint': 'マップマーカー',
               'overhead': '頭上メッセージ'}
QUALITY_LABELS = {'start_unobserved': '会話開始が未観測', 'incomplete_context': '会話が中断・不完全',
                  'dialogue_issue': '会話の対応に問題あり', 'invalid_time': '時刻が不正・逆行',
                  'assumed_boundary': '途中取得に基づく会話', 'unmatched_reply': '対応しない応答',
                  'ambiguous_interval': '区間の対応が不明', 'overlapping_prompt': '入力要求の重複', 'unanswered_termination': '未応答のままサーバー終了（タイムアウト疑い）'}


class DialoguePanel(QWidget):
    def __init__(self, store, show_source, *, names=None):
        super().__init__()
        self.store, self.show_source = store, show_source
        self.names=names if names is not None else empty_client_names()
        self.revision = -1
        self._refreshed_store = None
        self._json_state = None
        layout = QVBoxLayout(self)
        self.caption = QLabel('Auriga会話候補。起因・変数判定は生成対象外です。')
        layout.addWidget(self.caption)
        actions = QHBoxLayout()
        self.selection = QComboBox()
        self.selection.currentIndexChanged.connect(self.refresh_selected)
        actions.addWidget(self.selection, 1)
        for title, callback in [('生成形式を再読込', self.refresh_selected), ('根拠パケット', self.jump),
                                ('コード保存…', lambda: self.save(False)), ('会話JSON保存…', lambda: self.save(True))]:
            button = QPushButton(title)
            if title == 'コード保存…':
                menu = QMenu(button)
                menu.addAction('会話本文を保存…', callback)
                menu.addAction('配置付きNPCファイルを保存…', self.save_npc_file)
                button.setMenu(menu)
            else:
                button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        merge_actions = QHBoxLayout()
        self.merge_checkbox = QCheckBox('同一NPCの観測経路を統合')
        self.merge_checkbox.toggled.connect(self.refresh_selected)
        merge_actions.addWidget(self.merge_checkbox)
        self.merge_status = QLabel()
        self.merge_status.setWordWrap(True)
        merge_actions.addWidget(self.merge_status, 1)
        merge_save = QPushButton('統合JSON保存…')
        merge_save.clicked.connect(self.save_merged)
        merge_save.setToolTip('統合した会話の根拠を保存します。配置付きコードの全件出力は上部の出力メニューから行います。')
        merge_actions.addWidget(merge_save)
        layout.addLayout(merge_actions)
        self._merge_key = None
        self._merge_report = None
        split = QSplitter(Qt.Vertical)
        self.splitter = split
        split.setChildrenCollapsible(False)
        self.code, self.evidence = QPlainTextEdit(), DeferredJsonView(ensure_current=self.ensure_json_current)
        self.code.setReadOnly(True)
        self.evidence.setReadOnly(True)
        self.code.setPlaceholderText('NPCへ話しかけると、観測した経路のコード候補を表示します。')
        split.addWidget(self.code)
        details = QTabWidget()
        self.details_tabs = details
        details.setUsesScrollButtons(True)
        timeline_page = QWidget()
        timeline_layout = QVBoxLayout(timeline_page)
        self.timing_caption = QLabel('時間差は取得時刻の実測値です。サーバーのタイマー設定値ではありません。')
        self.timing_caption.setWordWrap(True)
        timeline_layout.addWidget(self.timing_caption)
        self.timeline = QTableWidget(0, 8)
        self.timeline.setHorizontalHeaderLabels(['開始から ms', '直前から ms', '入力要求から ms',
                                                '区間', '操作／表示', 'PacketID', '品質', '対象・本文・クエスト参考値'])
        self.timeline.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline.setSelectionMode(QAbstractItemView.SingleSelection)
        self.timeline.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.timeline.setColumnWidth(2, 130)
        self.timeline.setColumnWidth(3, 170)
        self.timeline.setColumnWidth(4, 130)
        self.timeline.itemDoubleClicked.connect(lambda _: self.jump())
        timeline_layout.addWidget(self.timeline)
        timeline_layout.addWidget(QLabel(
            '資源変化の命令採用（Zeny／アイテム／マップ）。起因は未確定のまま。未確認行はコメントのみ。'))
        self.resource_adoption = QTableWidget(0, 4)
        self.resource_adoption.setHorizontalHeaderLabels(['採用', '種別', '要約', 'Packet'])
        self.resource_adoption.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.resource_adoption.setSelectionMode(QAbstractItemView.SingleSelection)
        self.resource_adoption.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.resource_adoption.setMaximumHeight(140)
        self.resource_adoption.setColumnWidth(0, 50)
        self.resource_adoption.setColumnWidth(1, 110)
        self.resource_adoption.setColumnWidth(2, 280)
        self.resource_adoption.itemChanged.connect(self.toggle_resource_adoption)
        timeline_layout.addWidget(self.resource_adoption)
        details.addTab(timeline_page, '時間経過')
        self.timing_comparison = TimingComparisonPanel(store, show_source)
        details.addTab(self.timing_comparison, '反復比較')
        self.presentations = DeferredJsonView(ensure_current=self.ensure_json_current)
        self.presentations.setReadOnly(True)
        details.addTab(self.presentations, '並行・会話外演出')
        self.external_presentations = ExternalPresentationPanel(
            show_source, store=store, on_changed=self._external_adoption_changed)
        details.addTab(self.external_presentations, '対象別通知')
        self.event_trials = EventTrialPanel(store, show_source)
        review_page = QWidget()
        review_layout = QVBoxLayout(review_page)
        review_layout.addWidget(QLabel('統合除外の確認一覧。開始操作・条件・欠けた本文は補完しません。'))
        self.review_table = QTableWidget(0, 5)
        self.review_table.setHorizontalHeaderLabels(['会話', 'NPC / マップ', '状態', '統合除外理由', '根拠Packet'])
        self.review_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.review_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.review_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.review_table.setColumnWidth(1, 220)
        self.review_table.setColumnWidth(3, 170)
        self.review_table.cellDoubleClicked.connect(self.open_review)
        review_layout.addWidget(self.review_table)
        review_button = QPushButton('選択項目の会話・先頭根拠を開く')
        review_button.clicked.connect(self.open_review)
        review_layout.addWidget(review_button)
        details.addTab(review_page, '統合除外の確認')
        details.addTab(self.evidence, '根拠JSON')
        split.addWidget(details)
        self.code.setMinimumHeight(100)
        details.setMinimumHeight(180)
        split.setStretchFactor(0,2)
        split.setStretchFactor(1,3)
        split.setSizes([260,360])
        layout.addWidget(split,1)

    def refresh(self):
        if self._refreshed_store is self.store and self.revision == self.store.revision:
            return
        selected = self.selection.currentIndex()
        self.selection.blockSignals(True)
        self.selection.clear()
        for item in self.store.sessions:
            name = item.npc.get('name') or f'NPC {item.actor_id}'
            self.selection.addItem(f'会話 {item.id} · {name} · {item.status}')
        self.selection.setCurrentIndex(max(0, min(selected, len(self.store.sessions) - 1)))
        self.selection.blockSignals(False)
        self.revision = self.store.revision
        self._refreshed_store = self.store
        self.caption.setText('Auriga会話候補。起因・変数判定は生成対象外。'
                             f' 会話 {len(self.store.sessions)}件 / 解析問題 {self.store.issue_count}件（JSONに記録）')
        self.refresh_selected()
        self.refresh_review()

    def refresh_review(self):
        # Queue generation needs references only, not another deep copy of all
        # dialogue/resource evidence on each live refresh.
        conversations = (dict(capture_session=item.capture_session, id=item.id, actor_id=item.actor_id,
                              npc=item.npc, status=item.status, observed_open=item.observed_open,
                              steps=item.steps) for item in self.store.sessions)
        rows = build_review_queue(conversations, self.merged_report())
        labels = {'open_unobserved': '開始操作未観測', 'conversation_incomplete': '取消し・中断・未完了',
                  'npc_identity_incomplete': 'NPC識別情報不足', 'observation_quality': '観測品質の要確認',
                  'reply_or_layout_conflict': '応答・構造の不一致', 'step_capacity': 'ステップ上限',
                  'timeout_prefix_unmatched': '未応答終了の前方一致なし',
                  'timeout_additional_evidence_review': '未応答終了の追加観測を要確認',
                  'semantic_capacity': '意味データ上限', 'node_capacity': '統合ノード上限'}
        self.review_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [row['conversation_id'], f'{row["npc_name"] or row["actor_id"]} / {row["map_name"] or "不明"}',
                      {'closed': '終了', 'cancelled': '取消し', 'interrupted': '中断',
                       'map_changed': 'マップ移動'}.get(row['status'], row['status']),
                      labels.get(row['reason'], row['reason']),
                      f'{row["first_packet_index"]}〜{row["last_packet_index"]}']
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, row)
                cell.setToolTip(json.dumps(row, ensure_ascii=False))
                self.review_table.setItem(index, column, cell)

    def open_review(self, *args):
        row = self.review_table.currentRow()
        cell = self.review_table.item(row, 0) if row >= 0 else None
        if cell is None:
            return
        reference = cell.data(Qt.UserRole)
        index = next((i for i, item in enumerate(self.store.sessions)
                      if item.capture_session == reference['capture_session']
                      and item.id == reference['conversation_id']), None)
        if index is None:
            return
        self.selection.setCurrentIndex(index)
        if reference['first_packet_index'] is not None:
            self.show_source(reference['first_packet_index'])

    def selected(self):
        index = self.selection.currentIndex()
        return self.store.sessions[index] if 0 <= index < len(self.store.sessions) else None

    def renderer(self):
        from reconstruction.identity_protection import identity_from_player
        window = self.window()
        players = getattr(window, 'players', None)
        item = self.selected()
        state = None
        if players is not None and item is not None:
            flow = item.flow_id
            state = players.states.get((item.capture_session, flow))
            if state is None:
                state = players.states.get((0, flow))
        return AurigaRenderer(identity=identity_from_player(state))

    def json_state(self):
        item=self.selected()
        return (self.store,self.store.revision,id(item),tuple(sorted(self.store.source_refs.items())),self.merge_checkbox.isChecked())

    def ensure_json_current(self):
        # Packet ingestion may precede the regular view refresh. Rebuild both the
        # timeline and conversation source before materializing a stale document.
        if self._json_state!=self.json_state():
            if self._refreshed_store is not self.store or self.revision!=self.store.revision:
                self.refresh()
            else:self.refresh_selected()

    def refresh_selected(self, *args):
        self._json_state=self.json_state()
        self.timing_comparison.set_conversation(self.selected())
        self.event_trials.check_revision()
        self.presentations.set_document((self.store,self.store.revision),lambda store=self.store:dict(
            observations=store.presentation_observations,
            quest_observations=store.quest_observations, quest_dropped=store.quest_dropped,
            progress_observations=store.progress.snapshot(),
            dropped=store.presentation_dropped, script_commands=store.commands.observations,
            script_command_dropped=store.commands.dropped,
            note='入力待ち中・会話外を含む観測。会話が原因とは未確定。命令生成は種別ごとの条件に従い、元の受信順序はこの欄に保持します。'))
        item = self.selected()
        if item is None:
            self.external_presentations.set_conversation(None)
            self.code.clear()
            self.evidence.clear()
            self.timeline.setRowCount(0)
            self.resource_adoption.blockSignals(True)
            self.resource_adoption.setRowCount(0)
            self.resource_adoption.blockSignals(False)
            self.merge_status.clear()
            return
        timing = build_timeline(item, self.store.source_refs.get(item.capture_session, ''),
            player_notifications=index_player_notifications(self.store.presentation_observations))
        evidence_key=(self.store,self.store.revision,id(item),tuple(sorted(self.store.source_refs.items())),self.merge_checkbox.isChecked())
        evidence_document=lambda:dict(conversation=asdict(item),timeline=timing)
        self._fill_resource_adoption(item)
        self.timeline.setRowCount(len(timing['rows']))
        quest_fields = {record['packet_index']: record for record in item.resource_observations
                        if record['kind'].startswith('quest_')}
        item_actions = {record['packet_index']: record for record in item.actions
                        if record['fields'].get('command') in ('getitem','getitem2','delitem')}
        timeout_packets = {step['packet_index'] for step in item.steps if step.get('timeout_suspected')}
        for i, row in enumerate(timing['rows']):
            quest = quest_fields.get(row['packet_index'])
            reference = ''
            action = item_actions.get(row['packet_index']) if row.get('track') == 'conversation_action' else None
            if action:
                args = action['fields']['arguments']
                reference = f'ID={args["item_id"]} / 数量={args["amount"]} / '+item_name(self.names,args['item_id'])+'（品名資料）'
            if quest:
                fields = quest['fields']
                if quest['kind'] == 'quest_count':
                    reference = ' / '.join(quest_reference(self.names,entry['quest_id'])+f': {entry["current_count"]}/{entry["required_count"]}'
                                           for entry in fields['entries'])
                else:
                    reference = quest_reference(self.names,fields['quest_id'])
                    reference += f' / state={fields["state"]}（受信値）' if 'state' in fields else ' / 削除通知'
            if row.get('track') == 'player_notification':
                context={'during_dialogue':'会話中','input_wait':'入力待ち中','close_wait':'close応答待ち中'}.get(row['context'],row['context'])
                reference=f'対象PLAYER {row["actor_id"]} / 会話NPC {row["conversation_actor_id"]} / {context} / '+row['fields']['text']
            values = [row['elapsed_ms'], row['delta_ms'], row['wait_duration_ms'], INTERVAL_LABELS[row['interval']],
                      KIND_LABELS.get(row['kind'], row['kind']), f'0x{row["packet_id"]:04X}',
                      '本人通知・起因未確定' if row.get('track')=='player_notification' else '未応答終了・タイムアウト疑い' if row['packet_index'] in timeout_packets else '要確認' if row['flags'] else '', reference]
            for column, value in enumerate(values):
                cell = QTableWidgetItem('—' if value is None else str(value))
                cell.setData(Qt.UserRole, row['packet_index'])
                if action:
                    cell.setToolTip('名称資料はクライアントIDに対応します。サーバーDBのID一致・会話起因を確定しません。\n'+json.dumps(action['fields'],ensure_ascii=False))
                if quest:
                    cell.setToolTip(json.dumps(quest['fields'], ensure_ascii=False))
                self.timeline.setItem(i, column, cell)
        touch = item.npc.get('touch', {}) if is_touch(item.npc) else {}
        flags = ' / '.join(
            'クリック開始未観測（OnTouch候補・起因未確定）' if flag == 'start_unobserved' and touch
            else QUALITY_LABELS.get(flag, flag) for flag in timing['quality_flags']) or '時刻・応答の対応に問題なし'
        if touch:
            flags += f'\n接触範囲の候補: 半径X={touch["radius_x"]} / Y={touch["radius_y"]}。'
            flags += '範囲は暫定。' if touch.get('range_provisional') else '両軸の観測根拠あり（実装範囲の確定ではありません）。'
            if touch.get('range_basis') == 'walk_minimum_3x3':
                flags += '歩行先は到着を保証しないため、最小3×3セルを使用します。'
        self.timing_caption.setText(f'入力なし100ms以上: 比較対象 {len(timing["candidates"])}件 / '
                                   f'品質理由で除外 {len(timing["excluded_gaps"])}件。'
                                   f'サーバーのタイマー設定は未確定。通信欠落は未検証。\n{flags}')
        if timing['player_notification_count']:
            self.timing_caption.setText(self.timing_caption.text()+f'\n本人関連通知 {timing["player_notification_count"]}件（観測専用・詳細省略 {timing["player_notification_omitted"]}件）。待ち時間・反復集計には使用しません。')
        try:
            group = self.selected_group()
            self.external_presentations.set_conversation(item, group if self.merge_checkbox.isChecked() else None,
                                                         self.store.source_refs, self.store.presentation_observations,
                is_current=lambda store=self.store,revision=self.store.revision,sources=dict(self.store.source_refs):
                    self.store is store and store.revision==revision and store.source_refs==sources)
            renderer = self.renderer()
            check = group.get('presentation_check') if group else None
            warning = (f'演出不一致 {check["conflicts"]}経路 / 他ユーザー操作等の混入可能性・原因未確定'
                       if check and check['conflicts'] else '')
            if check and check['comparisons'] and not warning:
                consistent = sum(row['status'] == 'consistent_observations' for row in check['comparisons'])
                insufficient = sum(row['status'] == 'insufficient_observations' for row in check['comparisons'])
                warning = f'演出照合: 反復一致 {consistent}経路 / 比較不足 {insufficient}経路（原因未確定）'
            if self.merge_checkbox.isChecked():
                code = renderer.render_merged(group)
                self.merge_status.setText(f'{len(group["contributions"])}会話 / 不一致{len(group["conflicts"])}箇所（時間経過は選択会話）'
                                          if group else 'NPC識別・取得品質・会話の完了状態を確認してください')
                if group is None:
                    key = observation_key(self.store.source_refs.get(item.capture_session, ''), item)
                    excluded = next((row for row in self.merged_report()['excluded']
                        if (row['source_ref'], row['capture_session'], row['conversation_id']) == key), None)
                    if excluded and excluded['reason'] in ('node_capacity', 'semantic_capacity', 'step_capacity'):
                        self.merge_status.setText('統合データの保持上限に到達。根拠JSONを確認してください')
                excluded_rows=self.merged_report()['excluded']
                evidence_document=lambda:dict(conversation=asdict(item),timeline=timing,merged_group=group,excluded=excluded_rows)
            else:
                code = renderer.render(item, presentation_check=check)
                self.merge_status.clear()
            if warning:
                self.merge_status.setText((self.merge_status.text() + '\n' + warning).strip())
            if self.merge_checkbox.isChecked() and group and group.get('timeout_normalizations'):
                self.merge_status.setText(self.merge_status.text() + f' / 未応答終了の前方一致 {len(group["timeout_normalizations"])}件')
        except (OSError, ValueError) as exc:
            self.evidence.set_document(evidence_key,evidence_document)
            self.code.setPlainText(f'コード候補を生成できません: {exc}')
            return
        self.evidence.set_document(evidence_key,evidence_document)
        self.code.setPlainText(code)

    def merged_report(self):
        key = (self.store,self.store.revision, tuple(sorted(self.store.source_refs.items())))
        if key != self._merge_key:
            self._merge_report = build_merged((self.store.source_refs.get(item.capture_session, ''), item)
                                               for item in self.store.sessions)
            self._merge_key = key
        return self._merge_report

    def selected_group(self):
        item = self.selected()
        if item is None:
            return None
        key = observation_key(self.store.source_refs.get(item.capture_session, ''), item)
        return next((group for group in self.merged_report()['groups'] if any(
            (reference['source_ref'], reference['capture_session'], reference['conversation_id']) == key
            for reference in group['contributions'])), None)

    def export_protected_paths(self):
        paths = list(self.store.source_refs.values())
        definitions = getattr(self.window(), 'path', None)
        if definitions is not None:
            paths.append(definitions.text())
        return paths

    def save_merged(self):
        try:
            report = deepcopy(self.merged_report())
            renderer = self.renderer()
            result = dict(report, **renderer.render_groups(report['groups']),
                          source_sessions={str(key): value for key, value in self.store.source_refs.items()})
            protected = self.export_protected_paths()
            path, _ = QFileDialog.getSaveFileName(self, '統合観測と候補を保存', 'merged-npcs.json', 'JSON (*.json)')
            if path:
                save_observations(path, result, protected)
                if result['generation_errors']:
                    self.merge_status.setText(f'統合JSON保存済み / コード生成を停止した候補 {len(result["generation_errors"])}件')
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, '統合観測を保存できません', str(exc))

    def _fill_resource_adoption(self, item):
        labels = {'zeny': 'Zeny', 'item_gain': '所持品増加', 'item_loss': '所持品減少', 'map': 'マップ移動'}
        rows = [row for row in item.resource_observations if row['kind'] in labels]
        self.resource_adoption.blockSignals(True)
        self.resource_adoption.setRowCount(len(rows))
        for index, row in enumerate(rows):
            fields = row['fields']
            if row['kind'] == 'zeny':
                summary = (f"残高 {fields['value']} / 差分 {fields['delta']}" if fields['delta_known']
                           else f"残高 {fields['value']} / 差分不明（命令化不可）")
            elif row['kind'] == 'map':
                summary = f"{fields['map_name']} ({fields['x']},{fields['y']})"
            else:
                summary = f"ID={fields['item_id']} / 数量={fields['amount']} / Index {fields['index']}"
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked if row.get('adoption_confirmed') else Qt.Unchecked)
            check.setData(Qt.UserRole, row['packet_index'])
            if row['kind'] == 'zeny' and not fields.get('delta_known'):
                check.setFlags(Qt.ItemIsSelectable)
                check.setToolTip('差分不明のZenyは命令候補へ採用できません。')
            self.resource_adoption.setItem(index, 0, check)
            self.resource_adoption.setItem(index, 1, QTableWidgetItem(labels[row['kind']]))
            self.resource_adoption.setItem(index, 2, QTableWidgetItem(summary))
            self.resource_adoption.setItem(index, 3, QTableWidgetItem(f"0x{row['packet_id']:04X}"))
        self.resource_adoption.blockSignals(False)

    def toggle_resource_adoption(self, cell):
        if cell is None or cell.column() != 0:
            return
        item = self.selected()
        packet_index = cell.data(Qt.UserRole)
        if item is None or packet_index is None:
            return
        try:
            self.store.set_resource_adoption(item, packet_index, cell.checkState() == Qt.Checked)
        except ValueError as exc:
            self.resource_adoption.blockSignals(True)
            cell.setCheckState(Qt.Unchecked)
            self.resource_adoption.blockSignals(False)
            QMessageBox.warning(self, '命令採用を変更できません', str(exc))
            return
        self.revision = -1
        self.refresh_selected()

    def _external_adoption_changed(self):
        self.revision = -1
        self.refresh_selected()

    def jump(self):
        item = self.selected()
        row = self.timeline.currentRow()
        if row >= 0 and self.timeline.item(row, 0):
            self.show_source(self.timeline.item(row, 0).data(Qt.UserRole))
            return
        if item and item.steps:
            self.show_source(item.steps[0]['packet_index'])

    def save(self, as_json):
        item = self.selected()
        if item is None and not as_json:
            return
        try:
            renderer = self.renderer() if not as_json else None
            result = (deepcopy(self.store.snapshot()) if as_json else
                      renderer.render_merged(self.selected_group()) if self.merge_checkbox.isChecked() else
                      renderer.render(item, presentation_check=(self.selected_group() or {}).get('presentation_check')))
            protected = self.export_protected_paths()
            path, _ = QFileDialog.getSaveFileName(self, '会話を保存',
                                                 'dialogues.json' if as_json else f'conversation-{item.id}.txt')
            if path:
                if as_json:
                    save_observations(path, result, protected)
                else:
                    save_observation_text(path, result, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, '保存できません', str(exc))

    def save_npc_file(self):
        item = self.selected()
        if item is None:
            return
        try:
            group = self.selected_group()
            if self.merge_checkbox.isChecked() and group is None:
                raise ValueError('統合対象の会話を選択してください。')
            text = self.renderer().render_npc_file(item, group if self.merge_checkbox.isChecked() else None,
                                                  (group or {}).get('presentation_check'))
            protected = self.export_protected_paths()
            path, _ = QFileDialog.getSaveFileName(self, '配置付きNPC編集用候補を保存',
                                                 f'npc-conversation-{item.id}.txt', 'Auriga script (*.txt)')
            if path:
                save_observation_text(path, text, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'NPC候補を保存できません', str(exc))
