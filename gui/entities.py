"""NPC/MOB observation views backed by the semantic world store."""
from datetime import datetime
from reconstruction.entity_metadata import render_entity_metadata
from reconstruction.actor_appearance import declaration_class
from reconstruction.actor_identity import actor_sort_key
from gui.appearance_history import AppearanceHistoryPanel
from gui.adaptive_tabs import CurrentPageTabs

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget, QTabWidget)

STATES = {'visible': '表示中', 'removed': '消滅通知', 'dead': '死亡通知',
          'previous_map': 'マップ移動前', 'past_capture': '過去の観測', 'replaced': '別種別へ更新'}
COLUMNS = [('名前', 'name'), ('ActorID', 'actor_id'), ('外見／クラス', 'class_id'), ('マップ', 'map_name'),
           ('X', 'x'), ('Y', 'y'), ('向き', 'direction'), ('速度', 'speed'), ('状態', 'state'), ('更新件数', 'observations')]


class EntityTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        entity = self.rows[index.row()]
        if role == Qt.UserRole:
            return entity.key
        if role == Qt.ToolTipRole:
            return f'観測セッション {entity.capture_session} / マップ世代 {entity.map_generation} / 視界観測区間 {entity.appearance}（ID再割当の世代ではありません）'
        if role == Qt.DisplayRole:
            field = COLUMNS[index.column()][1]
            value = getattr(entity, field)
            if field == 'name' and not value:
                diagnostic = entity.metadata_evidence.get('name_diagnostic', {})
                if diagnostic.get('valid_prefix'):
                    return diagnostic['valid_prefix']+'（不完全名・参考）'
            if field == 'state':
                return STATES.get(value, value)
            return '未取得' if value is None or value == '' else str(value)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return COLUMNS[section][0] if orientation == Qt.Horizontal else section + 1
        return None

    def replace(self, records):
        self.beginResetModel()
        self.rows = list(records)
        self.endResetModel()


class EntityPanel(QWidget):
    def __init__(self, kind, on_export, on_source, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.on_source = on_source
        self.records = []
        self.actor_history = None
        self.appearance_history = AppearanceHistoryPanel(on_source,self)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.action_bar = bar
        self.count = QLabel('0 件')
        self.active_only = QCheckBox('表示中のみ')
        self.export_button = QPushButton(f'{kind}一覧を保存…')
        self.source_button = QPushButton('最後の根拠パケット')
        self.source_button.setEnabled(False)
        self.source_button.clicked.connect(self.open_source)
        self.export_button.clicked.connect(lambda: on_export(kind))
        bar.addWidget(self.count)
        bar.addWidget(self.active_only)
        bar.addStretch(1)
        bar.addWidget(self.source_button)
        bar.addWidget(self.export_button)
        layout.addLayout(bar)
        splitter = QSplitter(Qt.Vertical)
        self.splitter = splitter
        self.skill_panel = None
        self.performance_panel = None
        self.table = QTableView()
        self.model = EntityTableModel(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for index, width in enumerate((180, 100, 96, 130, 48, 48, 48, 60, 112, 70)):
            self.table.setColumnWidth(index, width)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText('行を選択すると、移動先・観測時刻・根拠パケットを確認できます。')
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setSizes([390, 130])
        layout.addWidget(splitter)
        layout.addWidget(QLabel('未取得の項目は推測しません。消滅通知は画面外への移動を含み、出現記録は再出現回数を意味しません。'))
        self.table.selectionModel().currentRowChanged.connect(self.show_selected)
        self.active_only.toggled.connect(self._filter)

    def attach_skills(self, panel):
        self.attach_observation('使用スキル', panel)
        self.skill_panel = panel

    def attach_observation(self, title, panel):
        tabs = CurrentPageTabs(self.splitter)
        self.details_tabs = tabs
        self.detail.setParent(None)
        self.splitter.insertWidget(1, tabs)
        tabs.addTab(self.detail, '個体情報')
        tabs.addTab(panel, title)
        self.splitter.setStretchFactor(0,1)
        self.splitter.setStretchFactor(1,1)
        self.splitter.setSizes([260,280])

    def attach_performance(self, panel):
        self.performance_panel = panel
        self.details_tabs.addTab(panel, '性能観測')

    def set_records(self, records):
        self.records = sorted(records, key=actor_sort_key)
        self._filter()

    def attach_actor_history(self):
        from gui.actor_history import ActorHistoryPanel
        self.actor_history = ActorHistoryPanel(self.on_source)
        self.details_tabs.addTab(self.actor_history, '同サーバー・同IDの観測')
        self.details_tabs.addTab(self.appearance_history, '外見変更履歴')

    def _filter(self):
        current = self.table.currentIndex()
        selected = self.model.data(current, Qt.UserRole) if current.isValid() else None
        appearance_selection = self.appearance_history.selected_key()
        rows = [entity for entity in self.records if not self.active_only.isChecked() or entity.active]
        self.model.replace(rows)
        self.count.setText(f'{len(rows)} 件 / 観測総数 {len(self.records)} 件')
        self.detail.clear()
        self.appearance_history.set_entity(None)
        self.source_button.setEnabled(False)
        if self.actor_history:
            self.actor_history.set_entity(None, [])
        if self.skill_panel:
            self.skill_panel.set_entity(None)
        if self.performance_panel:
            self.performance_panel.set_entity(None)
        if selected is not None:
            for row, entity in enumerate(rows):
                if entity.key == selected:
                    self.table.setCurrentIndex(self.model.index(row, 0))
                    self.appearance_history.select_key(appearance_selection)
                    break

    def show_selected(self, *args):
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.model.rows):
            if self.actor_history:
                self.actor_history.set_entity(None, [])
            self.detail.clear()
            self.appearance_history.set_entity(None)
            self.source_button.setEnabled(False)
            return
        entity = self.model.rows[index.row()]
        self.appearance_history.set_entity(entity)
        if self.actor_history:
            self.actor_history.set_entity(entity, self.records)
        if self.skill_panel:
            self.skill_panel.set_entity(entity.key)
        if self.performance_panel:
            self.performance_panel.set_entity(entity.key)
        self.source_button.setEnabled(bool(entity.evidence))
        def value(item):
            return '未取得' if item is None else str(item)
        options = '未取得' if entity.options is None else f'0x{entity.options:08X}'
        server = entity.server_endpoint
        server_label = f'{server["ip"]}:{server["port"]}' if server else '未取得'
        lines = [f'{self.kind}: {entity.name or "未取得"} / ActorID {entity.actor_id}',
                 f'サーバー: {server_label} / IDの割当方式: ' + ('インスタンス実行時割当' if '@' in (entity.map_name or '') else '未判定（連番だけでは静的配置と確定しません）'),
                 f'観測セッション {entity.capture_session} / マップ世代 {entity.map_generation} / 視界観測区間 {entity.appearance}（ID再割当とは別）',
                 f'状態: {STATES.get(entity.state, entity.state)} / オプション: {options}',
                 '初回観測オプション: ' + ('未取得' if entity.initial_options is None else f'0x{entity.initial_options:08X}') + '（出現定義に使用）',
                 f'移動先: {value(entity.destination_x)}, {value(entity.destination_y)}',
                 f'HP通知値: {value(entity.hp)} / {value(entity.max_hp)} / 割合通知（5%刻み）: {value(entity.hp_percent)}',
                 f'グループ: {value(entity.group_id)} / タイトル: '
                 + (repr(entity.title) if 'title' in entity.metadata_evidence else '未取得'),
                 f'接続: {entity.connection}', '根拠パケット（直近32件）:']
        initial = entity.initial_display
        lines.insert(-1, '外見class: 初回 ' + value(initial.get('class_id'))
                     + ' / 現在 ' + value(entity.class_id))
        if entity.kind == 'NPC':
            lines.insert(-1, '配置class: ' + value(declaration_class(vars(entity))))
            flag = entity.showevent_flag
            kind_flag = entity.showevent_kind
            flag_text = '未観測(-1)' if flag < 0 else str(flag)
            kind_text = '未観測(-1)' if kind_flag < 0 else str(kind_flag)
            label = ' / ラベル(9999)' if entity.showevent_label else ''
            lines.insert(-1, f'showeventflag: {flag_text} / kind: {kind_text}{label}')
        first_visual = initial.get('appearance_data') or {}
        current_visual = entity.appearance_data
        if first_visual or current_visual:
            lines.insert(-1, '外見の観測値（初回 → 最終取得値。未通知項目は更新しません）:')
            for key, label in (('sex','性別'),('hair_style','髪型'),('hair_color','髪色'),
                               ('cloth_color','服色'),('head_top','頭上段'),('head_mid','頭中段'),
                               ('head_bottom','頭下段'),('robe','衣装'),('style','style')):
                lines.insert(-1, '  ' + label + ': ' + value(first_visual.get(key))
                             + ' → ' + value(current_visual.get(key)))
        diagnostic = entity.metadata_evidence.get('name_diagnostic')
        if diagnostic:
            lines.insert(-1, '名前末尾のCP932文字が不完全です。切り詰めの疑いがあり、確定名へ採用しません。')
            lines.insert(-1, '参考接頭部分: '+diagnostic['valid_prefix'])
            lines.insert(-1, f'名前の受信範囲: offset {diagnostic["name_offset"]} / {diagnostic["observed_bytes"]} bytes / RAW '+diagnostic['raw_hex'])
        if entity.field_issues:
            lines.insert(-1, '未解決の項目: ' + ', '.join(entity.field_issues))
        for reference in entity.evidence:
            time = datetime.fromtimestamp(reference['timestamp']).strftime('%H:%M:%S.%f')[:-3]
            lines.append(f'  #{reference["packet_index"]} {time} 0x{reference["packet_id"]:04X} {reference["source"]}')
        try:
            text, _ = render_entity_metadata(dict(kind=entity.kind, actor_id=entity.actor_id, name=entity.name,
                group_id=entity.group_id, title=entity.title, metadata_evidence=entity.metadata_evidence,
                field_issues=entity.field_issues))
            if text:
                lines.extend(['', text])
                for field, label in (('group_id', 'グループ'), ('title', 'タイトル')):
                    if field in entity.metadata_evidence:
                        reference = entity.metadata_evidence[field]
                        lines.append(f'{label}の取得根拠: Packet #{reference["packet_index"]} / 0x0ADF')
        except (ValueError, OSError) as exc:
            lines.append(f'グループ・タイトル書式を表示できません: {exc}')
        self.detail.setPlainText('\n'.join(lines))

    def open_source(self):
        index = self.table.currentIndex()
        if index.isValid() and index.row() < len(self.model.rows):
            entity = self.model.rows[index.row()]
            if entity.evidence:
                self.on_source(entity.evidence[-1]['packet_index'])
