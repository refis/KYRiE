"""User-selected presentation anchors, kept separate from generated NPC code."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QPlainTextEdit, QFileDialog, QMessageBox, QTabWidget, QMenu, QSplitter)
from reconstruction.event_trials import compare_event_trials, event_semantics, trial_review
from reconstruction.comparison_anchors import comparison_rows
from reconstruction.event_timer_export import (
    COMMENT_TIMER_KINDS, TIMER_PRESENTATION_KINDS, validate_timer_trial)
from gui.presentation_context import presentation_context
from storage.event_trial_selection import save_selection, load_selection
from storage.observation_export import save_observation_text

STATUS = {'observed_difference': '観測列が不一致・混入/欠落等の原因は未確定',
    'insufficient_repeats': '比較不足', 'repeated_consistent': '反復一致・タイマー未確定',
    'repeated_variable': '時間差に変動あり', 'no_eligible_trials': '品質条件を満たす試行なし',
    'no_followup_observed': '基準点以降の演出は未観測'}
DIFFERENCES = {'same':'内容一致', 'target_changed':'対象が異なる', 'kind_changed':'種別が異なる',
    'content_changed':'内容が異なる', 'additional':'追加観測', 'unobserved':'参照側のみ観測', 'no_reference':'比較参照なし'}
EXCLUSIONS = {'target_different_map':'作用先が別MAP・別インスタンス', 'target_name_ambiguous':'作用先NPC名に省略の可能性',
    'target_unresolved':'作用先の配置情報不足', 'outside_visibility':'視界外での変更', 'review_only':'要確認の命令候補', 'after_close_reply':'close応答後の通知',
    'input_wait':'入力待ち中', 'close_wait':'close応答待ち中', 'during_dialogue':'会話中',
    'external_candidate':'別NPCへの外部演出候補', 'different_target':'基準と異なる対象',
    'invalid_time':'時刻不正・経過時間を算出不可', 'time_reversed':'時刻が逆行',
    'event_limit':'1試行1000演出の保持上限',
    'different_map':'基準と異なるMAP・世代', 'next_boundary':'次の会話開始・MAP移動以降', 'other_context':'対象外の記録状況'}
TIMER_ROLES = {'command': '実行命令候補', 'comment': 'コメント採用のみ', 'rejected': 'タイマー拒否'}

QUALITY = {'overlapping_windows': '観測窓が重複', 'invalid_time': '時刻不正・逆行',
           'event_limit': '演出保持上限', 'assumed_boundary': '途中取得'}
KINDS = {'visibility_action':'NPC表示状態', 'status_action':'状態変化（クライアントID）',
    'progress_action':'プログレスバー通知', 'script_command':'会話内命令候補', 'npc_display_action':'NPC外見変更',
    'dialogue_start': '会話開始', 'map_arrival': 'マップ到着', 'emotion': 'エモーション', 'effect': 'エフェクト', 'sound': '効果音', 'cutin': 'カットイン',
         'music': 'BGM（対象未特定）', 'mapcell': 'マップセル変更',
         'effect_remove': 'エフェクト解除',
         'effect_value': '値付きエフェクト',
         'dialogue_size':'会話サイズ', 'dialogue_position':'会話位置', 'dialogue_alignment':'会話整列',
    'classchange': '外見変更', 'progressbar': 'プログレスバー',
         'viewpoint': 'マップマーカー', 'overhead': '頭上メッセージ', 'announcement': 'アナウンス（起因未確定）',
         'player_chat': '本人向け発言通知', 'unittalk': 'ユニット発言',
         'event_marker': 'イベントアイコン', 'hat_effect': '帽子エフェクト'}


def labeled(mapping, code):
    """Show Japanese text with the stable reason/status code for discrimination."""
    text = mapping.get(code)
    if text is None:
        return str(code)
    return f'{text}（{code}）'


def difference_label(status):
    return labeled(DIFFERENCES, status)


def exclusion_label(reason):
    return labeled(EXCLUSIONS, reason)


def timer_role_code(kind):
    if kind in COMMENT_TIMER_KINDS:
        return 'comment'
    if kind in TIMER_PRESENTATION_KINDS:
        return 'command'
    if kind is None:
        return None
    return 'rejected'


def timer_role_label(kind):
    code = timer_role_code(kind)
    if code is None:
        return '—'
    return labeled(TIMER_ROLES, code)

def speech_description(row):
    evidence = row.get('speech_origin')
    if not isinstance(evidence, dict):
        return '発言由来の照合情報なし。'
    origin = evidence.get('origin')
    if origin == 'send_match_candidate':
        text = f'本人入力のSEND関連候補（send_match_candidate）: Packet #{evidence.get("send_packet_index", "不明")}。'
    elif origin == 'ambiguous_send_candidates':
        text = f'同文のSEND候補が複数（{evidence.get("candidate_count", "不明")}件）あり、一意に照合できません。'
    else:
        reason = {'unsupported_layout':'未対応の発言形式です。',
                  'self_actor_unknown':'本人ActorIDが未取得です。',
                  'different_actor':'観測済みの本人ActorIDとは異なる発言元です。',
                  'non_chat_notification':'本人宛ての頭上通知です。通常チャットのSEND照合対象外です。',
                  'no_matching_send':'条件を満たすSENDがありません。未取得・本文違い・範囲外などが考えられます。'}.get(evidence.get('reason'),'由来を判定する根拠が不足しています。')
        text = '発言由来は未確定。'+reason
    return text+' スクリプト由来や因果関係を確定するものではありません。'


def speech_send_index(row):
    evidence = row.get('speech_origin') or {}
    number = evidence.get('send_packet_index')
    received = row.get('packet_index')
    if (evidence.get('origin') == 'send_match_candidate' and evidence.get('self_actor_confirmed') is True
            and evidence.get('association_only') is True and evidence.get('send_packet_id') == 0x8c
            and type(number) is int and type(received) is int and 0 <= number < received):
        return number
    return None


class EventTrialPanel(QWidget):
    def __init__(self, store, on_source):
        super().__init__()
        self.store, self.on_source = store, on_source
        self.rows, self.report, self.report_key = [], None, None
        self.current_review = None
        self.exclusion_rows = []
        self.snapshot_revision = -1
        self.snapshot_observation_key = None
        layout = QVBoxLayout(self)
        self.note = QLabel('演出一覧を更新し、同じNPC・同じ会話外演出の基準点を2〜20件選択してください。')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        actions = QHBoxLayout()
        actions.addWidget(QLabel('比較基準'))
        self.anchor_mode = QComboBox()
        for label, value in (('会話外演出','presentation'),('会話開始','dialogue_start'),('マップ到着','map_arrival')):
            self.anchor_mode.addItem(label, value)
        self.anchor_mode.currentIndexChanged.connect(self.refresh)
        actions.addWidget(self.anchor_mode)

        for label, callback in [('演出一覧を更新', self.refresh), ('選択基準点で比較', self.compute),
                                ('比較JSON保存…', self.save), ('選択行の根拠', self.jump)]:
            button = QPushButton(label)
            if label == '比較JSON保存…':
                button.setText('保存・再開…')
                menu = QMenu(button)
                menu.addAction('比較結果JSONを保存…', callback)
                menu.addAction('基準点と観測窓を保存…', self.save_anchors)
                menu.addAction('保存した基準点を読み込む…', self.load_anchors)
                button.setMenu(menu)
            else:
                button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        window_actions=QHBoxLayout()
        self.window_actions=window_actions
        window_actions.addWidget(QLabel('観測窓 ms'))
        self.window = QSpinBox()
        self.window.setRange(1, 60000)
        self.window.setValue(5000)
        self.window.valueChanged.connect(self.invalidate)
        window_actions.addWidget(self.window)
        window_actions.addStretch(1)
        layout.addLayout(window_actions)
        options=QHBoxLayout()
        self.include_actions=QCheckBox('会話アクションも比較（会話開始のみ）')
        self.include_actions.setEnabled(False)
        self.include_actions.toggled.connect(self.refresh)
        options.addWidget(self.include_actions)
        options.addWidget(QLabel('会話元と作用先を分け、起因・タイマーは未確定として扱います。'))
        options.addStretch(1)
        layout.addLayout(options)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['取得', 'Packet', '時刻', '対象・音源／会話元', 'マップ', '記録状況', '演出'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnWidth(3, 160)
        self.table.setColumnWidth(6, 240)
        self.table.itemSelectionChanged.connect(self.invalidate)
        self.comparison_splitter=QSplitter(Qt.Vertical)
        self.comparison_splitter.setChildrenCollapsible(False)
        observation_page=QWidget()
        observation_layout=QVBoxLayout(observation_page)
        observation_layout.setContentsMargins(0,0,0,0)
        observation_layout.addWidget(self.table,1)
        self.table.setMinimumHeight(100)
        self.comparison_splitter.addWidget(observation_page)
        speech_row = QHBoxLayout()
        self.speech_note = QLabel('発言の観測行を選択すると由来の照合根拠を表示します。')
        self.speech_note.setWordWrap(True)
        self.speech_note.setTextFormat(Qt.PlainText)
        speech_row.addWidget(self.speech_note, 1)
        self.speech_source = QPushButton('発言のSEND根拠')
        self.speech_source.setEnabled(False)
        self.speech_source.clicked.connect(self.jump_speech_send)
        speech_row.addWidget(self.speech_source)
        observation_layout.addLayout(speech_row)
        self.table.itemSelectionChanged.connect(self.show_speech_origin)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.results = QTabWidget()
        page = QWidget()
        result_layout = QVBoxLayout(page)
        caption = QLabel('参照は最初の比較可能試行です。相違は観測内容の違いであり、原因や欠落を確定しません。')
        caption.setWordWrap(True)
        result_layout.addWidget(caption)
        self.trials = QTableWidget(0, 7)
        self.trials.setHorizontalHeaderLabels(['試行', '採否・理由', '観測列', '演出数', '入力等除外', '基準Packet', '参照との最初の相違'])
        self.trials.setColumnWidth(1, 190)
        self.trials.setColumnWidth(6, 240)
        self.trials.setSelectionBehavior(QTableWidget.SelectRows)
        self.trials.setSelectionMode(QTableWidget.SingleSelection)
        self.trials.setEditTriggers(QTableWidget.NoEditTriggers)
        self.trials.itemSelectionChanged.connect(self.show_trial_events)
        self.trials.setMinimumHeight(100)
        for column in (4,5,6):self.trials.setColumnHidden(column,True)
        self.trials.setColumnWidth(0,45)
        self.trials.setColumnWidth(2,55)
        self.trials.setColumnWidth(3,65)
        self.result_splitter=QSplitter(Qt.Horizontal)
        self.result_splitter.setChildrenCollapsible(False)
        self.result_splitter.addWidget(self.trials)
        event_page=QWidget()
        event_layout=QVBoxLayout(event_page)
        event_layout.setContentsMargins(0,0,0,0)
        self.result_splitter.addWidget(event_page)
        self.result_splitter.setSizes([350,780])
        self.result_splitter.setStretchFactor(0,1)
        self.result_splitter.setStretchFactor(1,2)
        result_layout.addWidget(self.result_splitter,1)
        self.events = QTableWidget(0, 7)
        self.events.setHorizontalHeaderLabels(
            ['基準からms', '種別', '観測内容', 'Packet', '対象', 'タイマー扱い', '参照との差'])
        self.events.setColumnWidth(2, 280)
        self.events.setColumnWidth(5, 150)
        self.events.setColumnWidth(6, 180)
        self.events.setSelectionBehavior(QTableWidget.SelectRows)
        self.events.setSelectionMode(QTableWidget.SingleSelection)
        self.events.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events.setMinimumHeight(100)
        event_layout.addWidget(self.events,1)
        source = QPushButton('選択演出の根拠')
        source.clicked.connect(self.jump_event)
        result_actions=QHBoxLayout()
        result_actions.addWidget(source)
        self.adopt_button = QPushButton('手入力タイマー候補…')
        self.adopt_button.clicked.connect(self.adopt_timer)
        self.adopt_button.setEnabled(False)
        result_actions.addWidget(self.adopt_button)
        self.adoption_note = QLabel('比較して採用対象の試行を選択してください。')
        self.adoption_note.setWordWrap(True)
        self.adoption_note.setTextFormat(Qt.PlainText)
        result_layout.addWidget(self.adoption_note)
        self.events.itemSelectionChanged.connect(self.show_event_difference)
        self.event_difference = QPlainTextEdit()
        self.event_difference.setReadOnly(True)
        self.event_difference.setMinimumHeight(60)
        self.event_difference.setMaximumHeight(100)
        event_layout.addWidget(self.event_difference)
        self.reference_source = QPushButton('参照側の根拠')
        self.reference_source.setEnabled(False)
        self.reference_source.clicked.connect(self.jump_reference_event)
        result_actions.insertWidget(1,self.reference_source)
        result_layout.addLayout(result_actions)
        self.results.addTab(page, '試行・演出')
        excluded_page = QWidget()
        excluded_layout = QVBoxLayout(excluded_page)
        self.exclusion_note = QLabel('同じ取得・フローの窓内候補と、時刻不正・逆行で位置を確認できない観測の除外理由を表示します。')
        self.exclusion_note.setWordWrap(True)
        excluded_layout.addWidget(self.exclusion_note)
        self.exclusions = QTableWidget(0, 5)
        self.exclusions.setHorizontalHeaderLabels(['基準からms','対象','種別','除外理由','Packet'])
        self.exclusions.setSelectionBehavior(QTableWidget.SelectRows)
        self.exclusions.setSelectionMode(QTableWidget.SingleSelection)
        self.exclusions.setEditTriggers(QTableWidget.NoEditTriggers)
        self.exclusions.setColumnWidth(1,180)
        self.exclusions.setColumnWidth(3,230)
        excluded_layout.addWidget(self.exclusions)
        excluded_source = QPushButton('除外した観測の根拠パケット')
        excluded_source.clicked.connect(self.jump_excluded_event)
        excluded_layout.addWidget(excluded_source)
        self.results.addTab(excluded_page,'除外した観測')

        timing_page = QWidget()
        timing_layout = QVBoxLayout(timing_page)
        self.timing_note = QLabel('同じ観測列の後続演出について、基準点からの経過msを集計します。設定待機時間ではありません。\n'
                                 '3試行未満は比較不足。後続演出が未観測、または全試行除外なら集計行はありません。')
        self.timing_note.setWordWrap(True)
        timing_layout.addWidget(self.timing_note)
        self.timing_rows = []
        self.timings = QTableWidget(0, 8)
        self.timings.setHorizontalHeaderLabels(['観測列', '演出', '試行数', '最小ms', '中央値ms', '最大ms', '幅ms', '判定'])
        self.timings.setColumnWidth(1, 150)
        self.timings.setColumnWidth(7, 230)
        self.timings.setSelectionBehavior(QTableWidget.SelectRows)
        self.timings.setSelectionMode(QTableWidget.SingleSelection)
        self.timings.setEditTriggers(QTableWidget.NoEditTriggers)
        self.timings.itemSelectionChanged.connect(self.show_timing_samples)
        timing_layout.addWidget(self.timings)
        self.timing_samples = QTableWidget(0, 5)
        self.timing_samples.setHorizontalHeaderLabels(['試行', '取得世代', '基準からms', 'Packet', '出典'])
        self.timing_samples.setColumnWidth(4, 240)
        self.timing_samples.setSelectionBehavior(QTableWidget.SelectRows)
        self.timing_samples.setSelectionMode(QTableWidget.SingleSelection)
        self.timing_samples.setEditTriggers(QTableWidget.NoEditTriggers)
        timing_layout.addWidget(self.timing_samples)
        timing_source = QPushButton('選択した時間差の根拠パケット')
        timing_source.clicked.connect(self.jump_timing_sample)
        timing_layout.addWidget(timing_source)
        self.results.addTab(timing_page, '時間差集計')
        self.results.addTab(self.detail, '結果JSON')
        self.comparison_splitter.addWidget(self.results)
        self.comparison_splitter.setStretchFactor(0,2)
        self.comparison_splitter.setStretchFactor(1,3)
        self.comparison_splitter.setSizes([220,380])
        layout.addWidget(self.comparison_splitter,1)

    def selected_indices(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows())

    def observation_key(self):
        # References may change independently of observation revision. Include the
        # store identity so equal revisions from different replays cannot match.
        sources = tuple(sorted((type(key).__name__, str(key), str(value))
                               for key, value in self.store.source_refs.items()))
        return self.store, self.store.revision, sources

    def current_key(self):
        return self.observation_key(), self.anchor_mode.currentData(), self.include_actions.isChecked(), self.window.value(), tuple(self.selected_indices())

    def invalidate(self, *args):
        self.report, self.report_key = None, None
        self.adopt_button.setEnabled(False)
        self.adoption_note.setText('比較して採用対象の試行を選択してください。')
        self.detail.clear()
        self.trials.setRowCount(0)
        self.events.setRowCount(0)
        self.current_review = None
        self.event_difference.clear()
        self.reference_source.setEnabled(False)
        self.exclusion_rows = []
        self.exclusions.setRowCount(0)
        self.exclusion_note.setText('同じ取得・フローの窓内候補と、時刻問題で除外した観測の理由を表示します。')
        self.timing_rows = []
        self.timings.setRowCount(0)
        self.timing_samples.setRowCount(0)

    def check_revision(self):
        if self.report is not None and self.report_key != self.current_key():
            self.invalidate()
            self.note.setText('観測が更新されています。演出一覧を更新して基準点を選び直してください。')
        if self.snapshot_observation_key != self.observation_key():
            self.show_speech_origin()

    def evidence_source(self, row):
        sources = self.report['source_sessions'] if self.report else self.store.source_refs
        session = row['capture_session']
        source = sources.get(session) or sources.get(str(session))
        return f'取得世代 {session} / フロー {row.get("flow_id", "不明")} / 出典: {source or "未登録"}'

    def retention_note(self):
        text = (f'演出の未保存 {self.store.presentation_dropped}件 / '
                f'MAP基準点の未保存 {self.store.map_anchor_dropped}件。')
        if self.include_actions.isChecked() and self.anchor_mode.currentData() == 'dialogue_start':
            text += f' 会話アクションの未保存 {getattr(self.store,"action_dropped",0)}件。'
        return text + ' 未保存件数は読込済み観測全体の値で、各試行への帰属は未確定。0件でも通信欠落・窓の全件取得を保証しません。'

    def refresh(self, *args):
        self.invalidate()
        self.include_actions.setEnabled(self.anchor_mode.currentData()=="dialogue_start")
        try:
            self.rows = comparison_rows(self.store, self.anchor_mode.currentData(),include_actions=self.include_actions.isChecked())
        except ValueError as exc:
            self.rows = []
            self.table.setRowCount(0)
            self.snapshot_revision = self.store.revision
            self.snapshot_observation_key = self.observation_key()
            self.note.setText(str(exc))
            return
        self.snapshot_revision = self.store.revision
        self.snapshot_observation_key = self.observation_key()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            try:
                time = datetime.fromtimestamp(row['timestamp']).strftime('%H:%M:%S.%f')[:-3]
            except (ValueError, OverflowError, OSError, TypeError):
                time = '時刻不正'
            context = {'outside_dialogue': '会話外', 'input_wait': '入力待ち中',
                       'close_wait': 'close応答待ち中', 'during_dialogue': '会話中',
                       'comparison_anchor': '比較基準点', 'external_candidate': '会話中・別NPCへの外部演出候補'}.get(row['context'], row['context'])
            kind = KINDS.get(row['kind'], row['kind'])
            subject=self.target_text(row) if presentation_context(row) else row.get('npc', {}).get('name') or ('マップ全体' if row.get('anchor_type')=='map_arrival' else f'{row["entity_kind"]} {row["actor_id"]}')
            values = [row['capture_session'], row['packet_index'], time,
                      subject,
                      row.get('npc', {}).get('map_name') or '不明', context,
                      kind + ' ' + json.dumps(row['fields'], ensure_ascii=False)]
            for column, value in enumerate(values):
                item=QTableWidgetItem(str(value))
                if column==3:item.setToolTip(str(value))
                self.table.setItem(index,column,item)
        self.note.setText(f'観測 {len(self.rows)}件 / '+self.retention_note()
                          +' 同じ種類の基準点を選択してください。起因は未確定。')

    def compute(self):
        self.invalidate()
        if self.snapshot_observation_key != self.observation_key():
            self.note.setText('観測が更新されています。演出一覧を更新して基準点を選び直してください。')
            return
        try:
            report = compare_event_trials(self.rows, self.selected_indices(), window_ms=self.window.value(),
                                          source_sessions=self.store.source_refs)
            report['presentation_dropped'] = self.store.presentation_dropped
            report['map_anchor_dropped'] = self.store.map_anchor_dropped
            if self.anchor_mode.currentData()=='dialogue_start' and self.include_actions.isChecked():
                report['include_dialogue_actions']=True
                report['action_dropped']=getattr(self.store,'action_dropped',0)
            self.report, self.report_key = report, self.current_key()
            text = json.dumps(report, ensure_ascii=False, indent=2)
            if len(text) > 200000:
                text = text[:200000] + '\n… 表示上限。全結果は比較JSON保存で確認してください。'
            self.detail.setPlainText(text)
            self.show_trial_summary()
            self.show_timing_summary()
            eligible = sum(not trial['quality_flags'] for trial in report['trials'])
            self.note.setText(STATUS[report['status']] + f'。比較対象 {eligible}/{len(report["trials"])}試行。'
                              '他ユーザー由来の可能性・窓の欠落は排除できません。'
                              +self.retention_note()+' NPCコードやタイマー値は生成しません。')
        except ValueError as exc:
            QMessageBox.warning(self, '演出を比較できません', str(exc))

    @staticmethod
    def first_difference(trial, reference, mode='presentation'):
        if reference is None:
            return '比較参照なし'
        left, right = trial['events'], reference['events']
        for index, (event, base) in enumerate(zip(left, right), 1):
            a, b = event['observation'], base['observation']
            left_values, right_values = event_semantics(a,mode), event_semantics(b,mode)
            if left_values[2:] != right_values[2:]:
                return f'演出{index}の対象が異なる'
            if left_values[:2] != right_values[:2]:
                return f'演出{index}の内容が異なる'
        if len(left) < len(right):
            return f'演出{len(left) + 1}以降を未観測'
        if len(left) > len(right):
            return f'演出{len(right) + 1}以降を追加観測'
        return '内容一致（時間差は各演出を参照）'

    def show_trial_summary(self):
        report = self.report
        reference = next((trial for trial in report['trials'] if not trial['quality_flags']), None)
        variants = {index: number for number, variant in enumerate(report['variants'], 1)
                    for index in variant['trial_indices']}
        self.trials.setRowCount(len(report['trials']))
        for index, trial in enumerate(report['trials']):
            reason = ' / '.join(QUALITY.get(flag, flag) for flag in trial['quality_flags'])
            values = [index + 1, '除外: ' + reason if reason else '比較対象', variants.get(index, '—'),
                      len(trial['events']), trial['excluded_input_or_parallel'], trial['anchor']['packet_index'],
                      self.first_difference(trial, reference, report.get('anchor_type','presentation')) if not reason else '比較対象外']
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (0,1,5):
                    item.setToolTip(self.evidence_source(trial['anchor'])+'\n'+str(values[6])+f' / 基準Packet #{trial["anchor"]["packet_index"]}')
                self.trials.setItem(index, column, item)
        if report['trials']:
            self.trials.selectRow(0)
            self.show_trial_events()

    def selected_trial(self):
        index = self.trials.currentRow()
        if self.report is not None and 0 <= index < len(self.report['trials']):
            return self.report['trials'][index]
        return None

    def show_timing_summary(self):
        self.timing_rows = [(variant_index, timing) for variant_index, variant in enumerate(self.report['variants'])
                            for timing in variant['timings']]
        self.timings.setRowCount(len(self.timing_rows))
        for index, (variant_index, timing) in enumerate(self.timing_rows):
            variant = self.report['variants'][variant_index]
            event = self.report['trials'][variant['trial_indices'][0]]['events'][timing['event_index']]['observation']
            status = ('insufficient_repeats' if variant['count'] < 3 else
                      'repeated_consistent' if timing['observed_consistent'] else 'repeated_variable')
            values = [variant_index + 1, f'{timing["event_index"] + 1}: {KINDS.get(event["kind"], event["kind"])}',
                      variant['count'], timing['min_ms'], timing['median_ms'], timing['max_ms'],
                      timing['spread_ms'], STATUS[status]]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setToolTip(json.dumps(event['fields'], ensure_ascii=False))
                self.timings.setItem(index, column, item)
        if self.timing_rows:
            self.timings.selectRow(0)
            self.show_timing_samples()
        else:
            self.timing_samples.setRowCount(0)

    def selected_timing(self):
        index = self.timings.currentRow()
        if self.report is not None and 0 <= index < len(self.timing_rows):
            return self.timing_rows[index]
        return None

    def show_timing_samples(self):
        selected = self.selected_timing()
        members = self.report['variants'][selected[0]]['trial_indices'] if selected else []
        self.timing_samples.setRowCount(len(members))
        for index, member in enumerate(members):
            trial = self.report['trials'][member]
            event = trial['events'][selected[1]['event_index']]
            row = event['observation']
            source_ref = self.report['source_sessions'].get(row['capture_session'], '')
            source_ref = source_ref or self.report['source_sessions'].get(str(row['capture_session']), '')
            source = Path(source_ref) if source_ref else None
            values = [member + 1, row['capture_session'], event['offset_ms'], row['packet_index'],
                      (source.parent.name or source.name) if source else '取得中']
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 4:
                    item.setToolTip(source_ref)
                self.timing_samples.setItem(index, column, item)
        if members:
            self.timing_samples.selectRow(0)

    def jump_timing_sample(self):
        self.check_revision()
        selected, index = self.selected_timing(), self.timing_samples.currentRow()
        if selected is None:
            return
        members = self.report['variants'][selected[0]]['trial_indices']
        if 0 <= index < len(members):
            event = self.report['trials'][members[index]]['events'][selected[1]['event_index']]
            packet = event['observation'].get('packet_index')
            if type(packet) is int and packet >= 0:
                self.on_source(packet)

    @staticmethod
    def target_text(row):
        if row.get('comparison_scope')=='dialogue_owner':
            owner=row.get('npc',{}).get('name') or str(row.get('actor_id'))
            target=row.get('effect_target',{})
            raw=row.get('raw_fields',{})
            raw_target=raw.get('target') or row.get('observed_target') or {}
            if raw.get('command')=='dropitem':raw_target=dict(name='床出現位置',map_name=raw['arguments'].get('map_name'))
            label=raw_target.get('name') or target.get('name') or {'player':'プレイヤー（ID未記録）','unassigned':'未特定','npc':'NPC（名称未取得）','dialogue_npc':'会話NPC'}.get(target.get('role'),'未特定')
            if raw_target.get('map_name'):label+=' ['+raw_target['map_name']+']'
            return '会話: '+owner+' / 作用先: '+label
        context=presentation_context(row)
        if context:
            if context['actor_role']=='dialogue_layout':return '会話表示: 対象ID未記録'
            if context['actor_role']=='map_cell':
                fields = row.get('fields', {})
                return f'セル: {fields.get("map_name", "不明")} ({fields.get("x")},{fields.get("y")})'
            name=row.get('npc',{}).get('name') or row.get('entity_kind') or '個体未確認'
            if context['actor_role']=='sound_origin':return f'音源: {name} / ID {row.get("actor_id")}'
            if context['actor_role']=='progress_target':return f'進捗対象: {name} / ID {row.get("actor_id")}'
            if context['actor_role']=='marker_npc':return f'通知NPC: {name} / ID {row.get("actor_id")}'
            if context['actor_role']=='effect_target':return f'効果対象: {name} / ID {row.get("actor_id")}'
            if context['actor_role']=='speech_source':return f'色付き発言: {name} / ID {row.get("actor_id")}'
            return 'BGM: 対象ID未記録' if row['kind']=='music' else '進捗: 対象ID未記録'
        npc = row.get('npc', {})
        if row.get('anchor_type') == 'map_arrival':
            return 'MAP ' + str(npc.get('map_name') or '不明')
        if row.get('actor_id') is None:
            return '対象未特定'
        return (npc.get('name') or row.get('entity_kind') or '対象未取得') + ' / ID ' + str(row['actor_id'])

    def reference_trial(self):
        return next((trial for trial in self.report['trials'] if not trial['quality_flags']),None) if self.report else None

    def show_adoption_status(self):
        self.adopt_button.setEnabled(False)
        if self.report is None:
            self.adoption_note.setText('比較して採用対象の試行を選択してください。')
            return
        if self.report_key != self.current_key():
            self.adoption_note.setText('比較条件・観測が更新されています。再比較してください。')
            return
        try:
            validate_timer_trial(self.report, self.trials.currentRow())
        except ValueError as exc:
            self.adoption_note.setText('手動タイマー候補の作成対象外: '+str(exc))
            return
        self.adopt_button.setEnabled(True)
        self.adoption_note.setText('手入力候補の編集へ進めます。全時刻の入力と確認が必要です。起因・タイマー設定・全件取得は未確定です。')

    def show_trial_events(self):
        self.show_adoption_status()
        trial = self.selected_trial()
        self.current_review = trial_review(self.report,self.trials.currentRow(),self.rows) if trial else None
        events = trial['events'] if trial else []
        differences = self.current_review['differences'] if self.current_review else []
        reference = self.reference_trial()
        self.events.setRowCount(0)
        self.events.setRowCount(len(differences))
        for index, difference in enumerate(differences):
            if index < len(events):
                event = events[index]
                row = event['observation']
                values = [event['offset_ms'], KINDS.get(row['kind'],row['kind']),
                          json.dumps(row['fields'],ensure_ascii=False),row['packet_index'],self.target_text(row),
                          timer_role_label(row.get('kind'))]
            else:
                row = reference['events'][index]['observation']
                values = ['—','未観測','参照側に観測あり（欠落とは未確定）','—','参照: '+self.target_text(row),
                          '—']
            values.append(difference_label(difference['status']))
            for column,value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 3:
                    item.setToolTip(('参照側: ' if index >= len(events) else '')+self.evidence_source(row))
                if column == 5 and index < len(events):
                    item.setToolTip('手動タイマー採用の扱い。比較列への掲載可否とは別です。')
                if column == 6:
                    item.setToolTip(str(difference['status']))
                self.events.setItem(index,column,item)
        self.exclusion_rows = self.current_review['excluded'] if self.current_review else []
        self.exclusions.setRowCount(0)
        self.exclusions.setRowCount(len(self.exclusion_rows))
        for index, excluded in enumerate(self.exclusion_rows):
            row = dict(excluded['observation'],npc=excluded['npc'])
            values = [excluded['offset_ms'] if excluded['offset_ms'] is not None else '算出不可',self.target_text(row),KINDS.get(row['kind'],row['kind']),
                      exclusion_label(excluded['reason']),row['packet_index']]
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value))
                if column==1:item.setToolTip(str(value))
                if column==3:item.setToolTip(str(excluded['reason']))
                if column==4:item.setToolTip(self.evidence_source(row))
                self.exclusions.setItem(index,column,item)
        if self.current_review:
            counts = ' / '.join(exclusion_label(key)+': '+str(value)
                                for key,value in self.current_review['excluded_counts'].items())
            self.exclusion_note.setText('同じ取得・フローの窓内候補／時刻問題の観測。'+(counts or '除外した観測なし')
                + f'。詳細省略 {self.current_review["omitted_details"]}件。採否・起因の判定は変更しません。')
        if differences:
            self.events.selectRow(0)
        self.show_event_difference()

    def show_event_difference(self):
        self.event_difference.clear()
        self.reference_source.setEnabled(False)
        trial, reference = self.selected_trial(),self.reference_trial()
        index = self.events.currentRow()
        if not trial or index < 0:
            return
        parts = []
        projected=False
        for label, candidate in (('選択試行',trial),('参照試行',reference)):
            if candidate is None or index >= len(candidate['events']):
                parts.append(label+': 対応する観測なし')
                continue
            event = candidate['events'][index]
            row = event['observation']
            projected=projected or row.get('comparison_scope')=='dialogue_owner'
            context=presentation_context(row)
            if context:parts.append(label+'の対象解釈: '+context['summary'])
            if row.get('speech_origin'):
                parts.append(label+'の発言由来: '+speech_description(row))
            parts.append(label+': '+self.target_text(row)+f' / Packet #{row["packet_index"]} / {event["offset_ms"]}ms\n'
                         + self.evidence_source(row)+'\n'
                         + KINDS.get(row['kind'],row['kind'])+' '+json.dumps(row['fields'],ensure_ascii=False))
        if projected:parts.append('作用先表示は生の名前・MAPです。比較では確認できた実行時接頭辞・接尾辞だけを正規化します。')
        self.event_difference.setPlainText('\n'.join(parts)+'\n同じ位置同士の照合です。挿入・欠落の自動整列や起因判定は行いません。')
        self.reference_source.setEnabled(bool(reference and index < len(reference['events'])))

    def jump_reference_event(self):
        self.check_revision()
        trial,index = self.reference_trial(),self.events.currentRow()
        if trial and 0 <= index < len(trial['events']):
            self.on_source(trial['events'][index]['observation']['packet_index'])

    def jump_excluded_event(self):
        self.check_revision()
        index = self.exclusions.currentRow()
        if self.report and 0 <= index < len(self.exclusion_rows):
            self.on_source(self.exclusion_rows[index]['observation']['packet_index'])

    def jump_event(self):
        self.check_revision()
        trial, index = self.selected_trial(), self.events.currentRow()
        if trial and 0 <= index < len(trial['events']):
            packet = trial['events'][index]['observation'].get('packet_index')
            if type(packet) is int and packet >= 0:
                self.on_source(packet)

    def show_speech_origin(self):
        self.speech_source.setEnabled(False)
        self.speech_source.setToolTip('')
        self.speech_note.setToolTip('')
        if self.snapshot_observation_key != self.observation_key():
            self.speech_note.setText('観測が更新されています。一覧を更新して発言を選び直してください。')
            return
        index = self.table.currentRow()
        if index not in [item.row() for item in self.table.selectionModel().selectedRows()] or not 0 <= index < len(self.rows):
            self.speech_note.setText('発言の観測行を選択すると由来の照合根拠を表示します。')
            return
        row = self.rows[index]
        context=presentation_context(row)
        self.speech_note.setText(context['short'] if context else speech_description(row))
        self.speech_note.setToolTip(context['summary'] if context else '')
        self.speech_source.setEnabled(speech_send_index(row) is not None)
        self.speech_source.setToolTip(self.evidence_source(row))

    def jump_speech_send(self):
        self.show_speech_origin()
        if not self.speech_source.isEnabled():
            return
        index = speech_send_index(self.rows[self.table.currentRow()])
        if index is not None:
            self.on_source(index)

    def jump(self):
        if self.snapshot_observation_key != self.observation_key():
            self.note.setText('演出一覧を更新してから根拠を選択してください。')
            return
        index = self.table.currentRow()
        if 0 <= index < len(self.rows):
            packet = self.rows[index].get('packet_index')
            if type(packet) is int and packet >= 0:
                self.on_source(packet)

    def adopt_timer(self):
        self.check_revision()
        index = self.trials.currentRow()
        if self.report is None or not 0 <= index < len(self.report['trials']):
            QMessageBox.information(self, '試行選択が必要です', '現在の観測で比較して、採用する試行を選択してください。')
            return
        from gui.event_timer_editor import EventTimerEditor
        report, key = self.report, self.report_key
        try:
            dialog = EventTimerEditor(report, index, self,
                is_current=lambda: self.report is report and self.current_key() == key)
        except ValueError as exc:
            QMessageBox.warning(self, '試行を採用できません', str(exc))
            return
        dialog.exec()
        dialog.deleteLater()

    def save_anchors(self):
        if self.snapshot_observation_key != self.observation_key():
            QMessageBox.information(self, '一覧更新が必要です', '演出一覧を更新して基準点を選び直してください。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '基準点と観測窓を保存', 'event-trial-selection.json', 'JSON (*.json)')
        if not path:
            return
        try:
            save_selection(path, self.rows, self.selected_indices(), self.store.source_refs, self.window.value(),
                settings=dict(mode=self.anchor_mode.currentData(), include_actions=(
                    self.anchor_mode.currentData() == 'dialogue_start' and self.include_actions.isChecked())))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '基準点を保存できません', str(exc))

    def load_anchors(self):
        path, _ = QFileDialog.getOpenFileName(self, '保存した基準点を読み込む', '', 'JSON (*.json)')
        if not path:
            return
        try:
            def rows_for(settings):
                mode = settings['mode'] if settings else self.anchor_mode.currentData()
                actions = settings['include_actions'] if settings else self.include_actions.isChecked()
                return comparison_rows(self.store, mode, include_actions=actions)
            indices, window, settings = load_selection(
                path, rows_for, self.store.source_refs, return_settings=True)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '基準点を読み込めません', str(exc) + '\n旧形式では保存時と同じ比較基準・会話アクション設定を選択してください。')
            return
        if settings is not None:
            with QSignalBlocker(self.anchor_mode), QSignalBlocker(self.include_actions):
                self.anchor_mode.setCurrentIndex(self.anchor_mode.findData(settings['mode']))
                self.include_actions.setChecked(settings['include_actions'])
            self.include_actions.setEnabled(settings['mode'] == 'dialogue_start')
        self.refresh()
        self.window.setValue(window)
        selection = self.table.selectionModel()
        for index in indices:
            selection.select(self.table.model().index(index, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.note.setText(f'基準点 {len(indices)}件と観測窓を復元しました。選択を確認して比較を実行してください。'+self.retention_note())

    def save(self):
        if self.report is None or self.report_key != self.current_key():
            QMessageBox.information(self, '比較が必要です', '現在の観測・選択・観測窓で比較してから保存してください。')
            return
        try:
            text = json.dumps(self.report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
            if len(text.encode('utf-8')) > 32 * 1024 * 1024:
                raise ValueError('比較JSONが32MiBを超えています。')
            protected = list(self.store.source_refs.values())
            definitions = getattr(QWidget.window(self), 'path', None)
            if definitions is not None:
                protected.append(definitions.text())
            path, _ = QFileDialog.getSaveFileName(self, '演出基準点比較を保存', 'event-trial-comparison.json', 'JSON (*.json)')
            if path:
                save_observation_text(path, text, protected)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '比較を保存できません', str(exc))
