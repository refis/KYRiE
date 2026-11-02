from version import __version__
from datetime import datetime
import sqlite3
import json
from gui.layout import build_workspace
from PySide6.QtCore import Qt, QTimer
from gui.packet_delivery import Bridge, PacketDelivery
from gui.view_limits import DISPLAY_LIMIT
from gui.event_history import MEMORY_EVENT_LIMIT, physical_index, trim_parallel
from gui.history_tasks import HistoryTasks
from gui.observation_save import ObservationTextSnapshot,ObservationSaveWorker
from collections import deque
from PySide6.QtWidgets import QMainWindow, QTableWidgetItem, QFileDialog, QMessageBox, QInputDialog
from capture.receiver import Receiver
from capture.process_monitor import list_processes
from scapy.interfaces import get_working_ifaces
from parser.definitions import load_lengths
from storage.database import PacketDatabase
from storage.session_log import SessionLog
from pathlib import Path
from ipc.server import PipeServer
from parser.display import CONFIG_ROOT, DEFAULT_PROFILE, DEFAULT_SEND_PROFILE, DisplayProfile, DisplayResult, ReceiveDisplay
from reconstruction.world import WorldStore
from reconstruction.dialogue import DialogueStore
from reconstruction.player import PlayerStore
from reconstruction.skills import SkillStore
from reconstruction.combat import CombatStore
from reconstruction.shops import ShopStore
from reconstruction.barter import BarterStore
from reconstruction.mob_spawns import MobSpawnStore
from parser.ignorepacket import IgnorePacket, observation_tags
from gui.ignorepacket import IgnorePacketDialog


class MainWindow(QMainWindow):
    def __init__(self, offline=False):
        super().__init__()
        self.offline = offline
        self.offline_windows = []
        self.setWindowTitle(f'KYRiE v{__version__} — Auriga復元ワークスペース')
        available = self.screen().availableGeometry()
        self.resize(max(900,min(1280,available.width()-48)),max(600,min(860,available.height()-64)))
        self.setMinimumSize(900,600)
        self.bridge = Bridge()
        self.bridge.packet.connect(self.add_packet)
        self.bridge.status.connect(self.show_capture_status)
        self.bridge.overflow.connect(self.packet_delivery_overflow)
        self.receiver = None
        self.pipe = None
        self.session_log = None
        self.log_error_reported = False
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(300)
        self.monitor_timer.timeout.connect(self.poll_connections)
        self.events = []
        self.observation_tags = []
        self.ignorepacket = IgnorePacket()
        ignore_error = ''
        try:
            self.ignorepacket = IgnorePacket.load()
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            ignore_error = f'ignorepacket設定を読み込めません: {exc}'
        self.display_results = []
        self.packet_indices=[]
        self.display_sessions = []
        self.event_origin = 0
        self.packet_rowids = []
        self.evicted_rowids = {}
        self.memory_event_limit = MEMORY_EVENT_LIMIT
        self.capture_session = 0
        self.packet_gui_received=0
        self.packet_processed=0
        self.packet_db_confirmed=0
        self.packet_db_unconfirmed=0
        self.database_failed=False
        self.world = WorldStore()
        self.mob_spawns = MobSpawnStore(self.world)
        self.shops = ShopStore(self.world)
        self.barters = BarterStore(self.world)
        self.players = PlayerStore()
        self.skills = SkillStore(self.world)
        self.combat = CombatStore(self.world)
        self.dialogues = DialogueStore(world=self.world)
        self.shops.dialogues = self.dialogues
        self.barters.dialogues = self.dialogues
        self.world_sources = {}
        from reconstruction.client_names import load_client_names, empty_client_names
        try:
            self.client_names=load_client_names()
        except (OSError,ValueError):
            self.client_names=empty_client_names()
        from reconstruction.navigation import load_navigation,empty_navigation
        try:
            self.navigation=load_navigation()
        except (OSError,ValueError):
            self.navigation=empty_navigation()
        self.dialogues.source_refs = self.world_sources
        self.world_revision = -1
        self.world_notified_issues = set()
        self.presenter = None
        self.send_presenter = None
        self.display_profile_paths = {'RECV': str(DEFAULT_PROFILE), 'SEND': str(DEFAULT_SEND_PROFILE)}
        self.display_input_paths=dict(self.display_profile_paths)
        self.selected_display_direction = 'RECV'
        self.db = PacketDatabase(':memory:' if offline else 'packets.sqlite3')
        build_workspace(self)
        self.display_export=None
        self.export_label="観測ログ"
        self.export_on_success=None
        self.last_export_summary=None
        self.close_after_display_export=False
        self.workspace_closing=False
        self.workspace_closed=False
        self.render_timestamps=False
        self.history_view_stale=False
        settings_error = self.apply_user_settings()
        self.history_tasks=HistoryTasks(self)
        self.history_tasks.changed.connect(self.history_update_state)
        self.history_tasks.failed.connect(self.history_update_failed)
        self.history_cancel.clicked.connect(lambda:self.history_tasks.cancel())
        self.history_refresh.clicked.connect(self.rebuild_display_log)
        self.display_save_cancel.clicked.connect(self.cancel_display_export)
        self.update_packet_progress()
        self.ignore_mob.setChecked(self.ignorepacket.mob_combat)
        self.ignore_mob.toggled.connect(self.toggle_ignore_mob)
        self.ignore_settings.clicked.connect(self.edit_ignorepacket)
        self.ignore_packet_selection.toggled.connect(self.toggle_selected_packet_ignore)
        self.ignore_npc_selection.toggled.connect(self.toggle_selected_npc_ignore)
        self.overlay_edit.clicked.connect(self.edit_overlay_structure)
        self.overlay_diff.clicked.connect(self.diff_same_id_instances)
        self.overlay_export.clicked.connect(self.export_confirmed_overlay)
        self.overlay_path.editingFinished.connect(self.sync_ignore_selection)
        self.table.itemSelectionChanged.connect(self.sync_ignore_selection)
        self.npc_panel.table.selectionModel().currentRowChanged.connect(self.sync_ignore_selection)
        self.npc_panel.model.modelReset.connect(self.sync_ignore_selection)
        self.entity_timer = QTimer(self)
        self.entity_timer.setInterval(250)
        self.entity_timer.timeout.connect(self.refresh_entity_views)
        self.entity_timer.start()
        self.workspace_tabs.currentChanged.connect(self.refresh_entity_views)
        self.bridge.connections.connect(self.show_connections)
        self.populate_processes()
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.packet_pager.changed.connect(self.render_packet_page)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.filter.textChanged.connect(self.apply_filter)
        self.display_browse.clicked.connect(self.browse_display)
        self.display_reload.clicked.connect(self.reload_display)
        self.display_timestamps.toggled.connect(self.reformat_display)
        self.display_unmapped.toggled.connect(self.rebuild_display_log)
        self.display_save.clicked.connect(self.save_display)
        self.settings_dialog.finished.connect(lambda *_: self.persist_user_settings())
        self.reload_display()
        try:
            send_path = self.display_input_paths.get('SEND') or str(DEFAULT_SEND_PROFILE)
            self.send_presenter = self._make_display(self._load_display_profile(send_path), direction='SEND')
        except (OSError, ValueError) as exc:
            self.show_capture_status(f'SEND display profile load failed: {exc}')
        self.process.currentIndexChanged.connect(self.update_capture_controls)
        self.update_capture_controls()
        if ignore_error:
            self.show_capture_status(ignore_error)
        if settings_error:
            self.show_capture_status(settings_error)

    def apply_user_settings(self):
        from storage import user_settings
        from reconstruction.emulator_profiles import set_target
        try:
            document = user_settings.load()
        except (OSError, user_settings.UserSettingsError) as exc:
            return f'ユーザー設定を読み込めません（既定値を使用）: {exc}'
        user_settings.apply_to_window(self, document)
        try:
            set_target(document['emulator'])
        except ValueError as exc:
            return f'ユーザー設定の出力形式を適用できません（既定値を維持）: {exc}'
        return ''

    def persist_user_settings(self):
        if self.workspace_closed:
            return
        from storage import user_settings
        try:
            user_settings.save(user_settings.collect_from_window(self))
        except (OSError, user_settings.UserSettingsError) as exc:
            self.show_capture_status(f'ユーザー設定を保存できません: {exc}')

    def edit_ignorepacket(self):
        dialog = IgnorePacketDialog(self.ignorepacket, self)
        if dialog.exec():
            self.ignorepacket = dialog.settings()
            self.ignore_mob.blockSignals(True)
            self.ignore_mob.setChecked(self.ignorepacket.mob_combat)
            self.ignore_mob.blockSignals(False)
            self.rebuild_display_log()
            self.sync_ignore_selection()

    def reload_ignorepacket(self):
        try:
            settings = IgnorePacket.load()
        except (OSError, ValueError) as exc:
            self.show_capture_status(f'非表示設定を再読込できません。現在の設定を保持します: {exc}')
            return
        self.ignorepacket = settings
        self.ignore_mob.blockSignals(True)
        self.ignore_mob.setChecked(settings.mob_combat)
        self.ignore_mob.blockSignals(False)
        self.rebuild_display_log()
        self.sync_ignore_selection()
        self.show_capture_status('非表示設定を再読込しました。')

    def retained_event(self, logical):
        return self.events[physical_index(logical, self.event_origin)]

    def sync_ignore_selection(self, *args):
        row = self.selected_packet_index()
        packet_id = self.retained_event(row).packet_id if row is not None else None
        index = self.npc_panel.table.currentIndex()
        rows = self.npc_panel.model.rows
        actor_id = rows[index.row()].actor_id if index.isValid() and 0 <= index.row() < len(rows) else None
        self.npc_metadata_export.setEnabled(actor_id is not None)
        for button, value, excluded in (
                (self.ignore_packet_selection, packet_id, self.ignorepacket.ids),
                (self.ignore_npc_selection, actor_id, self.ignorepacket.npc_actors)):
            button.blockSignals(True)
            button.setEnabled(value is not None)
            button.setChecked(value is not None and value in excluded)
            button.blockSignals(False)
        self.overlay_edit.setEnabled(packet_id is not None)
        selected = self.selected_packet_indices()
        self.overlay_diff.setEnabled(
            len(selected) == 2
            and self.retained_event(selected[0]).packet_id == self.retained_event(selected[1]).packet_id)
        self.overlay_export.setEnabled(bool(self.overlay_path.text().strip()))

    def toggle_selected_packet_ignore(self, checked):
        row = self.selected_packet_index()
        if row is not None:
            self.set_ignore_member('ids', self.retained_event(row).packet_id, checked)

    def toggle_selected_npc_ignore(self, checked):
        index = self.npc_panel.table.currentIndex()
        rows = self.npc_panel.model.rows
        if index.isValid() and 0 <= index.row() < len(rows):
            self.set_ignore_member('npc_actors', rows[index.row()].actor_id, checked)

    def set_ignore_member(self, field, value, checked):
        from dataclasses import replace
        members = set(getattr(self.ignorepacket, field))
        members.add(value) if checked else members.discard(value)
        if len(members) > (1000 if field == 'npc_actors' else 65536):
            self.show_capture_status('非表示リストの上限に達しています。設定画面でリストを整理してください。')
            self.sync_ignore_selection()
            return
        self.ignorepacket = replace(self.ignorepacket, **{field: frozenset(members)})
        self.rebuild_display_log()
        self.sync_ignore_selection()
        try:
            self.ignorepacket.save()
        except (OSError, ValueError) as exc:
            self.show_capture_status(f'非表示設定は適用済みですが保存できません: {exc}')

    def toggle_ignore_mob(self, checked):
        from dataclasses import replace
        self.ignorepacket = replace(self.ignorepacket, mob_combat=checked)
        self.rebuild_display_log()
        try:
            self.ignorepacket.save()
        except (OSError, ValueError) as exc:
            self.show_capture_status(f'非表示設定は適用済みですが保存できません: {exc}')

    def show_capture_status(self, message):
        brief = message
        if message.startswith('Opening Npcap interfaces:'):
            brief = '観測する接続を準備しています。'
        elif message.startswith('Npcap capture ready;'):
            brief = '観測準備ができました。ゲームへログイン／再接続してください。'
        elif 'framing stopped' in message.lower():
            brief = '解析を停止した接続があります。「診断」で詳細を確認できます。'
        elif message.startswith('PASS HTTP'):
            brief = '対象外のHTTP通信を除外しました。'
        elif message.startswith('Session log:'):
            brief = 'セッション記録を開始しました。'
        elif message == 'Stopped':
            brief = '観測を停止しました。'
        elif message.startswith('Npcap capture failed:'):
            brief = '取得エラーが発生しました。「診断」で詳細を確認できます。'
        elif message.startswith('Entity observation failed:'):
            brief = 'NPC／MOB情報に未解決の項目があります。「診断」で確認できます。'
        self.statusBar().showMessage(brief)
        self.capture_log.appendPlainText(message)
        if self.session_log:
            self.session_log.write('status', message=message)

    def update_capture_summary(self):
        if self.offline:
            self.mode_summary.setText('保存ログの再解析（ライブ取得とは別の履歴）')
            self.observation_caption.setText('保存ログから再構築した観測。表示書式は設定から変更できます。')
            return
        target = 'Auriga' if self.emulator.currentData() == 'auriga' else 'rAthena'
        directions = '受信＋送信' if self.capture_send.isChecked() else '受信のみ'
        recording = '再解析データ: 保存' if self.record_stream.isChecked() else '再解析データ: 未保存'
        self.mode_summary.setText(f'{target} · {directions} · {recording}')
        self.observation_caption.setText(f'{target}向けの観測記録。表示形式は設定から変更できます。')

    def browse_definitions(self):
        path, _ = QFileDialog.getOpenFileName(self, 'パケット長定義を選択', self.path.text(), 'Text (*.txt);;All files (*)')
        if path:
            self.path.setText(path)

    def browse_overlay(self):
        start = self.overlay_path.text().strip() or str(Path(self.path.text()).parent)
        path, _ = QFileDialog.getOpenFileName(self, '構造オーバーレイを選択', start, 'JSON (*.json);;All files (*)')
        if path:
            self.overlay_path.setText(path)
            self.sync_ignore_selection()

    def edit_overlay_structure(self):
        row = self.selected_packet_index()
        if row is None:
            return
        from gui.overlay_editor import OverlayEditorDialog
        from parser.packet_overlay import find_overlay_packet
        event = self.retained_event(row)
        overlay = None
        try:
            overlay = self._load_optional_overlay()
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f'既存オーバーレイを読めません（新規として編集）: {exc}')
        seed = find_overlay_packet(overlay, event.packet_id)
        renderer = self.presenter if event.direction == 'RECV' else self.send_presenter
        rule = renderer.profile.rules.get(event.packet_id) if renderer else None
        default_path = self.overlay_path.text().strip() or str(
            Path(self.path.text()).resolve().parent / 'packet_overlay.json')
        dialog = OverlayEditorDialog(
            event.packet_id, len(event.raw), seed_entry=seed, display_rule=rule,
            overlay_path=default_path, parent=self)
        if dialog.exec():
            saved = dialog.saved_path()
            if saved:
                self.overlay_path.setText(saved)
                self.reload_display()
                self.show_selected()
                self.sync_ignore_selection()
                self.statusBar().showMessage(f'構造オーバーレイを保存し再解析しました: {saved}')

    def selected_packet_indices(self):
        indices = []
        seen = set()
        end = self.event_origin + len(self.events)
        for item in self.table.selectedItems():
            if item.column() != 0:
                continue
            index = item.data(Qt.UserRole)
            if type(index) is int and self.event_origin <= index < end and index not in seen:
                seen.add(index)
                indices.append(index)
        return indices

    def diff_same_id_instances(self):
        selected = self.selected_packet_indices()
        if len(selected) != 2:
            self.statusBar().showMessage('同一PacketIDのパケットを2件選択してください。')
            return
        left, right = self.retained_event(selected[0]), self.retained_event(selected[1])
        if left.packet_id != right.packet_id:
            self.statusBar().showMessage('選択した2件のPacketIDが一致しません。')
            return
        from parser.packet_overlay import (
            compare_same_id_instances, fields_from_display_rule, find_overlay_packet,
            format_instance_diff,
        )
        fields = {}
        try:
            overlay = self._load_optional_overlay()
            entry = find_overlay_packet(overlay, left.packet_id)
            if entry:
                fields = entry.get('fields') or {}
        except (OSError, ValueError):
            overlay = None
        if not fields:
            renderer = self.presenter if left.direction == 'RECV' else self.send_presenter
            rule = renderer.profile.rules.get(left.packet_id) if renderer else None
            fields = fields_from_display_rule(rule)
        try:
            report = compare_same_id_instances(left.raw, right.raw, fields=fields, packet_id=left.packet_id)
        except ValueError as exc:
            self.statusBar().showMessage(f'同一ID差分に失敗: {exc}')
            return
        text = format_instance_diff(report)
        self.hex.setPlainText(
            f'{text}\n\n--- A index={selected[0]} {left.connection} ---\n'
            f'--- B index={selected[1]} {right.connection} ---')
        self.statusBar().showMessage(
            f'同一ID差分 0x{left.packet_id:04X}: '
            + ('一致' if report['equal'] else f'{report["difference_count"]} 箇所'))

    def export_confirmed_overlay(self):
        try:
            overlay = self._load_optional_overlay()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'オーバーレイを読めません', str(exc))
            return
        if overlay is None:
            QMessageBox.information(self, 'エクスポート', '設定で構造オーバーレイのパスを指定してください。')
            return
        start = str(Path(self.overlay_path.text().strip()).resolve().parent)
        directory = QFileDialog.getExistingDirectory(self, 'オーバーレイ確定のエクスポート先', start)
        if not directory:
            return
        from parser.packet_overlay import write_overlay_exports
        try:
            result = write_overlay_exports(directory, overlay)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'エクスポートできません', str(exc))
            return
        self.statusBar().showMessage(
            f'オーバーレイ確定を書き出しました（{result["packet_count"]} ID）: '
            f'{result["lengths"]} / {result["display"]}')
        QMessageBox.information(
            self, 'エクスポート完了',
            'PacketLength／displayの本体は上書きしていません。\n'
            f'長さ: {result["lengths"]}\n表示断片: {result["display"]}')

    def _load_optional_overlay(self):
        path = self.overlay_path.text().strip()
        if not path:
            return None
        from parser.packet_overlay import load_overlay
        return load_overlay(path)

    def _load_display_profile(self, path):
        overlay = self._load_optional_overlay()
        if overlay is None:
            return DisplayProfile.load(path)
        from parser.packet_overlay import load_profile_with_overlay
        return load_profile_with_overlay(path, overlay)

    def _make_display(self, profile, direction='RECV'):
        return ReceiveDisplay(profile, direction=direction, client_names=getattr(self, 'client_names', None))

    def refresh_entity_views(self, *args):
        self.mob_spawn_panel.refresh()
        self.shop_panel.refresh()
        self.player_panel.refresh()
        self.dialogue_panel.refresh()
        self.mob_skills_panel.refresh()
        self.mob_performance_panel.refresh()
        if self.world_revision == self.world.revision:
            return
        self.npc_panel.set_records(self.world.records('NPC'))
        self.mob_panel.set_records(self.world.records('MOB'))
        self.world_revision = self.world.revision

    def save_entities(self, kind):
        if self.workspace_closing or self.display_export is not None:return
        from copy import deepcopy
        panel = self.npc_panel if kind == 'NPC' else self.mob_panel
        snapshot = deepcopy(self.world.snapshot(kind, active_only=panel.active_only.isChecked()))
        snapshot['source_sessions'] = dict(self.world_sources)
        protected = [*snapshot['source_sessions'].values(), self.path.text()]
        path, _ = QFileDialog.getSaveFileName(self, f'{kind}観測一覧を保存', f'{kind.lower()}-observations.json', 'JSON (*.json)')
        if path:
            try:
                self.save_report_export(path,snapshot,protected,label=f"{kind}一覧")
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, '一覧を保存できません', str(exc))

    def save_all_npcs(self):
        if self.workspace_closing or self.display_export is not None:return
        from reconstruction.npc_bundle import build_npc_bundle
        try:
            merge = self.dialogue_panel.merge_checkbox.isChecked()
            from dataclasses import asdict
            entities=[asdict(entity) for entity in self.world.records('NPC')]
            sources=dict(self.world_sources)
            large=(len(entities)>100 or len(self.dialogues.sessions)>50 or
                   sum(len(item.steps) for item in self.dialogues.sessions)>1000 or len(self.shops.records)>100)
            from reconstruction.identity_protection import identity_from_store
            from storage.user_settings import indent_value
            identity = identity_from_store(self.players)
            indent = indent_value(self.script_indent.currentData()) if hasattr(self, 'script_indent') else None
            prepared=None
            if large:
                from reconstruction.report_snapshot import freeze_npc_report
                prepared=freeze_npc_report(entities,self.dialogues.sessions,sources,merge=merge,
                                          shops=self.shops.records,barters=self.barters.records,identity=identity,
                                          client_names=getattr(self,'client_names',None), indent=indent)
            report=None if prepared is not None else build_npc_bundle(entities,self.dialogues.sessions,
                sources,merge=merge,shops=self.shops.records,barters=self.barters.records,identity=identity,
                client_names=getattr(self,'client_names',None), indent=indent)
            if report is not None and not report['entries'] and not report['excluded']:
                raise ValueError('NPCの観測がありません。')
            mode = '統合' if merge else '個別'
            path, _ = QFileDialog.getSaveFileName(self, f'全NPCを保存（会話: {mode}）',
                                                'all-placed-npcs-merged.txt' if merge else 'all-placed-npcs-individual.txt',
                                                'Auriga script (*.txt);;JSON (*.json)')
            if not path:
                return
            protected = [*sources.values(), self.path.text()]
            suffix=Path(path).suffix.lower()
            if suffix not in ('.json','.txt'):
                raise ValueError('保存形式は.txtまたは.jsonを指定してください。')
            if prepared is not None:
                from dataclasses import replace
                prepared=replace(prepared,text_output=suffix=='.txt')
                self.save_prepared_report(path,prepared,protected,label='全NPC出力',on_success=self.npc_export_saved)
                return
            def saved():
                self.show_capture_status(f'NPC {len(report["entries"])}配置を保存 / 除外 {len(report["excluded"])}件 / '
                    f'要確認 {report["review_only_count"]}件 / 会話 {mode}')
            self.save_report_export(path,report['auriga'] if suffix=='.txt' else report,protected,
                text=suffix=='.txt',label='全NPC出力',on_success=saved)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'NPC一括出力を保存できません', str(exc))

    def npc_export_saved(self):
        row=self.last_export_summary
        if row:
            mode='統合' if row['merge'] else '個別'
            self.show_capture_status(f'NPC {row["entries"]}配置を保存 / 除外 {row["excluded"]}件 / '
                f'要確認 {row["review_only_count"]}件 / 会話 {mode}')

    def save_npc_metadata(self):
        from dataclasses import asdict
        from reconstruction.auriga import AurigaRenderer
        from storage.observation_export import save_observations, save_observation_text
        index = self.npc_panel.table.currentIndex()
        rows = self.npc_panel.model.rows
        if not index.isValid() or not 0 <= index.row() < len(rows):
            return
        try:
            entity = asdict(rows[index.row()])
            from storage.user_settings import indent_value
            indent = indent_value(self.script_indent.currentData()) if hasattr(self, 'script_indent') else None
            code = AurigaRenderer(indent=indent).render_npc_metadata_file(entity)
            sources = dict(self.world_sources)
            path, _ = QFileDialog.getSaveFileName(self, 'NPCの配置・初期化のみを保存',
                                                f'npc-init-{entity["actor_id"]}.txt',
                                                'Auriga script (*.txt);;JSON (*.json)')
            if not path:
                return
            protected = [*sources.values(), self.path.text()]
            if Path(path).suffix.lower() == '.json':
                save_observations(path, dict(schema_version=1, kind='npc_metadata_only', entity=entity,
                    source_sessions=sources, auriga=code, dialogue_included=False), protected)
            elif Path(path).suffix.lower() == '.txt':
                save_observation_text(path, code, protected)
            else:
                raise ValueError('保存形式は.txtまたは.jsonを指定してください。')
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'NPC初期化を保存できません', str(exc))

    def show_entity_source(self, index):
        if type(index) is not int or index < 0:
            return
        if index < self.event_origin:
            self.workspace_tabs.setCurrentWidget(self.packet_page)
            self._show_evicted_packet(index)
            return
        if index >= self.event_origin + len(self.events):
            return
        self.filter.clear()
        self.schedule_history_view(immediate=True)
        self.workspace_tabs.setCurrentWidget(self.packet_page)
        position=self.packet_indices.index(index)
        self.packet_pager.page=position//DISPLAY_LIMIT
        self.packet_pager.follow_latest=False
        self.packet_pager._update()
        self.render_packet_page()
        row=position%DISPLAY_LIMIT
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 0))
        self.show_selected()

    def select_emulator_profile(self, index):
        from reconstruction.emulator_profiles import set_target
        target = self.emulator.currentData()
        path = CONFIG_ROOT / target / 'display.json'
        previous = getattr(self, 'last_emulator_index', 0)
        try:
            profile = self._load_display_profile(path)
        except (OSError, ValueError) as exc:
            self.show_capture_status(f'表示形式を変更できません（前の設定を維持）: {exc}')
            self.emulator.blockSignals(True)
            self.emulator.setCurrentIndex(previous)
            self.emulator.blockSignals(False)
            return
        def committed():
            try:
                set_target(target)
            except ValueError as exc:
                self.show_capture_status(f'表示形式を変更できません（前の設定を維持）: {exc}')
                self.emulator.blockSignals(True)
                self.emulator.setCurrentIndex(previous)
                self.emulator.blockSignals(False)
                return
            self.emulator.blockSignals(True)
            self.emulator.setCurrentIndex(index)
            self.emulator.blockSignals(False)
            self.last_emulator_index=index
            self.display_profile_paths['RECV']=str(path)
            self.display_input_paths['RECV']=str(path)
            if self.selected_display_direction.upper()=='RECV':
                self.display_path.setText(str(path))
            self.update_capture_summary()
        self._reformat_with(self._make_display(profile),on_complete=committed)

    def save_capture_log(self):
        from storage.observation_export import save_observation_text
        session = self.session_log
        text = self.capture_log.toPlainText() if session is None else None
        protected = [*self.world_sources.values(), self.path.text()]
        default = 'capture.jsonl' if session else 'capture-diagnostics.txt'
        path, _ = QFileDialog.getSaveFileName(self, 'Save diagnostic log', default,
                                            'Diagnostic logs (*.jsonl *.txt);;All files (*)')
        if not path:
            return
        try:
            target = Path(path)
            if session:
                session.export(target, protected)
            else:
                save_observation_text(target, text, protected)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'Cannot save diagnostic log', str(exc))

    def choose_interface(self):
        interfaces = get_working_ifaces()
        labels = ['Automatic: all usable Npcap adapters'] + [
            f'{iface.name} | {getattr(iface, "ip", "")} | {iface.network_name}' for iface in interfaces]
        selected, accepted = QInputDialog.getItem(self, 'Capture interface', 'Adapter', labels, 0, False)
        if accepted:
            index = labels.index(selected)
            self.iface.setText('' if index == 0 else interfaces[index - 1].network_name)

    def update_capture_controls(self):
        running = self.receiver is not None or self.offline
        manual = self.process.currentData() is None
        for control in (self.process, self.children, self.refresh_processes, self.iface,
                        self.interface_picker, self.path, self.definitions_browse, self.attach_existing,
                        self.pipe_enabled, self.pipe_name, self.record_stream, self.log_root, self.capture_send):
            control.setEnabled(not running)
        for control in (self.ip, self.port):
            control.setEnabled(not running and manual)
            control.setToolTip('Manual mode only; EXE tracking uses discovered sockets. Stop to change capture settings.')
        self.update_capture_summary()
        self.open_log_button.setEnabled(not running)
        self.open_project_action.setEnabled(not running)
        self.repair_project_action.setEnabled(not running)
        self.edit_project_sources_action.setEnabled(not running)
        self.open_logs_action.setEnabled(not running)
        if self.offline:
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(False)

    def open_recording(self):
        if self.receiver or self.offline:
            return
        path, _ = QFileDialog.getOpenFileName(self, '再解析用の生ログを開く',
                                            self.log_root.text(), 'Capture log (*.jsonl)')
        if not path:
            return
        from gui.offline import OfflineWindow
        try:
            definitions_path = Path(path).with_name('PacketLength.used.txt')
            if not definitions_path.is_file():
                definitions_path = Path(self.path.text())
            definitions = load_lengths(definitions_path)
            profiles = dict(self.display_profile_paths)
            profiles[self.selected_display_direction] = self.display_path.text()
            window = OfflineWindow(path, definitions, definitions_path, profiles, self)
            self.offline_windows.append(window)
            window.show()
            window.begin_replay()
        except (OSError, ValueError):
            QMessageBox.critical(self, 'ログを開けません', 'ログ・長さ定義・表示書式のファイルを確認してください。')

    def open_project(self):
        if self.receiver or self.offline:
            return
        path, _ = QFileDialog.getOpenFileName(self, '作業プロジェクトを開く', '', 'Project (*.gpa.json)')
        if not path:
            return
        from storage.project import load_project, fingerprint, config_limit, project_references, verify_runtime_catalogs
        from gui.offline import OfflineWindow
        try:
            project = load_project(path)
            verify_runtime_catalogs(project)
            files = project['files']
            for key, ref in project_references(project):
                if key != 'log' and fingerprint(ref['path'], config_limit(key)) != ref['sha256']:
                    raise ValueError('参照ファイルが変更されています。')
            from reconstruction.emulator_profiles import profile as generation_profile, TARGETS
            dialogue_path = Path(files['dialogue']['path']).resolve()
            allowed = {generation_profile('dialogue.json', name).resolve() for name in TARGETS}
            if dialogue_path not in allowed:
                raise ValueError('別の会話生成書式のパスは未対応です。')
            inputs = [(row['log']['path'], load_lengths(row['definitions']['path']), row['definitions']['path'])
                      for row in project.get('sources', [])]
            first = inputs[0] if inputs else (files['log']['path'], load_lengths(files['definitions']['path']), files['definitions']['path'])
            window = OfflineWindow(*first,
                                   {key: files[key.lower()]['path'] for key in ('RECV', 'SEND')}, self,
                                   project=project, inputs=inputs if project['schema'] == 2 else None)
            self.offline_windows.append(window)
            window.show()
            window.begin_replay()
        except (OSError, ValueError):
            QMessageBox.critical(self, 'プロジェクトを開けません',
                                 '参照ファイルの不足・変更、または作業ファイルの形式を確認してください。')

    def repair_project(self):
        if self.receiver or self.offline:
            return
        path, _ = QFileDialog.getOpenFileName(self, '修復する作業プロジェクトを選択', '', 'Project (*.gpa.json)')
        if not path:
            return
        from storage.project import load_project
        from gui.project_references import ProjectReferencesDialog
        try:
            ProjectReferencesDialog(load_project(path), path, self).exec()
        except (OSError, ValueError):
            QMessageBox.critical(self, '作業ファイルを開けません', 'プロジェクト形式を確認してください。')

    def edit_project_sources(self):
        if self.receiver or self.offline:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'ログ一覧を編集する作業プロジェクトを選択', '', 'Project (*.gpa.json)')
        if not path:
            return
        from storage.project import load_project
        from gui.project_sources import ProjectSourcesDialog
        try:
            ProjectSourcesDialog(load_project(path), path, self).exec()
        except (OSError, ValueError):
            QMessageBox.critical(self, '作業ファイルを開けません', 'プロジェクト形式を確認してください。')

    def open_recordings(self):
        if self.receiver or self.offline:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, '比較する生ログを選択', self.log_root.text(), 'Capture log (*.jsonl)')
        if not paths:
            return
        from gui.offline import OfflineWindow
        try:
            paths = list(dict.fromkeys(Path(path).resolve() for path in paths))
            if len(paths) > 20:
                raise ValueError('Too many logs')
            inputs = []
            for path in paths:
                definitions_path = path.with_name('PacketLength.used.txt')
                if not definitions_path.is_file():
                    definitions_path = Path(self.path.text())
                inputs.append((path, load_lengths(definitions_path), definitions_path))
            profiles = dict(self.display_profile_paths)
            profiles[self.selected_display_direction] = self.display_path.text()
            window = OfflineWindow(*inputs[0], profiles, self, inputs=inputs if len(inputs) > 1 else None)
            self.offline_windows.append(window)
            window.show()
            window.begin_replay()
        except (OSError, ValueError):
            QMessageBox.critical(self, '複数ログを開けません', 'ファイル数・長さ定義・表示書式を確認してください。')

    def save_project(self):
        pass  # Only a completed offline workspace can save a project.

    def edit_project_note(self):
        pass

    def browse_display(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Packet display profile', self.display_path.text(), 'JSON (*.json)')
        if path:
            self.display_path.setText(path)
            self.reload_display()

    def switch_display_direction(self, direction):
        self.display_input_paths[self.selected_display_direction] = self.display_path.text()
        self.selected_display_direction = direction
        self.display_path.setText(self.display_input_paths[direction])

    def reload_display(self):
        try:
            path=self.display_path.text()
            profile=self._load_display_profile(path)
            direction=self.selected_display_direction
            def committed():
                self.display_profile_paths[direction]=path
                self.display_input_paths[direction]=path
                label='受信' if direction=='RECV' else '送信'
                overlay='＋オーバーレイ' if self.overlay_path.text().strip() else ''
                self.statusBar().showMessage(f'表示定義を読み込みました（{label} {len(profile.rules)} 種類{overlay}）。')
            self._reformat_with(self._make_display(profile,direction=direction),direction=direction,on_complete=committed)
        except (OSError,ValueError) as exc:
            self.history_tasks.cancel('format')
            self.statusBar().showMessage(f'Display profile reload failed (previous profile retained): {exc}')

    def history_update_failed(self):
        self.history_view_stale=True
        self.statusBar().showMessage('表示更新に失敗しました。表示を再更新してください。')
        self.history_update_state()

    def history_update_state(self):
        busy=self.history_tasks.busy
        self.history_cancel.setEnabled(busy)
        self.history_progress.setText('表示更新中（前回の表示を維持）' if busy else
            '更新取消／失敗：表示を再更新してください' if self.history_view_stale else '')
        self.display_save.setEnabled(not self.workspace_closing and not busy and not self.history_view_stale and self.display_export is None)

    def restore_display_controls(self):
        self.display_timestamps.blockSignals(True)
        self.display_timestamps.setChecked(self.render_timestamps)
        self.display_timestamps.blockSignals(False)
        self.emulator.blockSignals(True)
        self.emulator.setCurrentIndex(getattr(self,'last_emulator_index',0))
        self.emulator.blockSignals(False)

    def _reformat_with(self,presenter,direction='RECV',on_complete=None):
        timestamps=self.display_timestamps.isChecked()
        self.history_tasks.cancel('format')
        self.display_timestamps.blockSignals(True)
        self.display_timestamps.setChecked(timestamps)
        self.display_timestamps.blockSignals(False)
        profiles={'RECV':self.presenter,'SEND':self.send_presenter}
        profiles[direction]=presenter
        renderers={key:self._make_display(value.profile,direction=key) for key,value in profiles.items() if value}
        def replay():
            results=[];previous_session=None;index=0
            while index<len(self.events):
                event=self.events[index];session=self.display_sessions[index]
                if session!=previous_session:
                    for renderer in renderers.values():renderer.reset()
                    previous_session=session
                renderer=renderers.get(event.direction)
                for other in renderers.values():
                    if other is not renderer:other.observe(event)
                results.append(renderer.decode(event,timestamps) if renderer else DisplayResult('','','skipped'))
                index+=1
                yield
            return results,previous_session
        def commit(value):
            results,previous_session=value
            if previous_session!=self.capture_session:
                for renderer in renderers.values():renderer.reset()
            self.presenter=renderers.get('RECV');self.send_presenter=renderers.get('SEND')
            self.display_results=results
            self.render_timestamps=timestamps
            if on_complete:on_complete()
            self.rebuild_display_log()
        self.history_tasks.start('format',replay(),commit,asynchronous=len(self.events)>2000,
                                 abort=self.restore_display_controls)

    def reformat_display(self):
        if self.presenter:
            self._reformat_with(self._make_display(self.presenter.profile))
        elif self.send_presenter:
            self._reformat_with(self._make_display(self.send_presenter.profile, direction='SEND'), direction='SEND')

    def display_visible(self, event, result, tags=None):
        return (self.matches(event) and bool(result.text) and
                not self.ignorepacket.hides(event, tags or {}) and
                (result.status != 'unmapped' or self.display_unmapped.isChecked()))

    def rebuild_display_log(self):
        self.ignore_summary.setText(f'除外ID {len(self.ignorepacket.ids)}件 / NPC '
                                    f'{len(self.ignorepacket.npc_actors) + len(self.ignorepacket.npc_names)}件')
        self.schedule_history_view()

    def schedule_history_view(self,*,immediate=False):
        query=self.filter.text().strip().lower().removeprefix('0x')
        ignored=self.ignorepacket
        unmapped=self.display_unmapped.isChecked()
        def project():
            indices=[];chunks=deque();size=0;index=0
            while index<len(self.events):
                event=self.events[index];result=self.display_results[index]
                logical=self.event_origin+index
                if not query or query in f'{event.packet_id:04x}':
                    indices.append(logical)
                    if result.text and not ignored.hides(event,self.observation_tags[index]) and (result.status!='unmapped' or unmapped):
                        text=result.text[-self.DISPLAY_TEXT_LIMIT:]
                        chunks.append(text);size+=len(text)+1
                        while chunks and size-len(chunks[0])-1>=self.DISPLAY_TEXT_LIMIT:
                            size-=len(chunks.popleft())+1
                index+=1
                yield
            return indices,'\n'.join(chunks)[-self.DISPLAY_TEXT_LIMIT:]
        def commit(value):
            self.history_view_stale=False
            indices,text=value
            self.packet_indices[:]=indices
            self.packet_pager.set_rows(self.packet_indices,'packets')
            self.display_log.setPlainText(self.bounded_display_text(text))
        def abort():self.history_view_stale=True
        self.history_tasks.start('view',project(),commit,
            asynchronous=not immediate and len(self.events)>2000,abort=abort)

    DISPLAY_TEXT_LIMIT=262144

    @classmethod
    def bounded_display_text(cls,text):
        return '\n'.join(text[-cls.DISPLAY_TEXT_LIMIT:].split('\n')[-5000:])

    def append_display_text(self,text):
        self.display_log.appendPlainText(MainWindow.bounded_display_text(text))
        if self.display_log.document().characterCount()>self.DISPLAY_TEXT_LIMIT+1:
            # Leave headroom so trimming is occasional rather than per packet.
            self.display_log.setPlainText(self.display_log.toPlainText()[-self.DISPLAY_TEXT_LIMIT*3//4:])

    def save_display(self):
        from storage.observation_export import save_observation_chunks,validate_export_destination,ExportLimitError
        if self.workspace_closing or self.display_export is not None:return
        if self.history_tasks.busy or self.history_view_stale:
            self.statusBar().showMessage('表示更新を完了してください。取消後は「表示を再更新」を実行してください。')
            return
        snapshot=ObservationTextSnapshot(self.events,self.display_results,self.observation_tags,
            len(self.events),self.filter.text().strip().lower().removeprefix('0x'),self.ignorepacket,
            self.display_unmapped.isChecked(),self.display_log.toPlainText() if not self.events else '')
        protected=[*self.world_sources.values(),self.path.text()]
        path,_=QFileDialog.getSaveFileName(self,'Save visible packet text','packets.txt','Text (*.txt)')
        if not path or self.workspace_closing:return
        protected.extend([*self.world_sources.values(),self.path.text()])
        try:
            validate_export_destination(path,protected)
            retained_note=(f'メモリ退避 {self.event_origin} 件は本文保存対象外（DBに保持）。'
                           if self.event_origin else '')
            if not snapshot.needs_worker:
                save_observation_chunks(path,snapshot,protected)
                self.statusBar().showMessage('観測ログを保存しました。'+retained_note)
                return
            self.start_file_export(path,snapshot,protected,label='観測ログ')
            if retained_note:
                self.show_capture_status(retained_note)
        except (OSError,ValueError) as exc:
            message=('観測出力は64MiB以内にしてください。' if isinstance(exc,ExportLimitError) else
                     '入力データ・保存先・空き容量・アクセス権を確認してください。保存を完了できませんでした。')
            QMessageBox.critical(self,'ファイルを保存できません',message)

    def save_report_export(self,path,report,protected,*,text=False,label='観測データ',on_success=None):
        from storage.observation_export import (observation_json_chunks,report_needs_worker,
            save_observation_chunks,validate_export_destination)
        if self.workspace_closing or self.display_export is not None:
            self.statusBar().showMessage('実行中の保存が終了してから操作してください。')
            return False
        protected=[*protected,*self.world_sources.values(),self.path.text()]
        validate_export_destination(path,protected)
        chunks=(report,) if text else observation_json_chunks(report)
        if report_needs_worker(report):
            self.start_file_export(path,chunks,protected,label=label,on_success=on_success)
        else:
            save_observation_chunks(path,chunks,protected)
            if on_success:on_success()
        return True

    def save_prepared_report(self,path,prepared,protected,*,label,on_success=None):
        from storage.observation_export import validate_export_destination
        if self.workspace_closing or self.display_export is not None:return False
        protected=[*protected,*self.world_sources.values(),self.path.text()]
        validate_export_destination(path,protected)
        self.start_file_export(path,None,protected,label=label,builder=prepared,on_success=on_success)
        return True

    def start_file_export(self,path,chunks,protected,*,label,on_success=None,builder=None):
        self.export_label=label
        self.export_on_success=on_success
        self.display_export=ObservationSaveWorker(path,chunks,protected,self,builder=builder)
        self.display_export.finished.connect(self.display_export_finished)
        self.display_save_cancel.setEnabled(True)
        self.display_save_cancel.show()
        self.display_save.setText(f'集計・保存中: {label}' if builder is not None else f'保存中: {label}')
        self.history_update_state()
        self.display_export.start()

    def cancel_display_export(self):
        if self.display_export is not None:
            self.display_export.requestInterruption()
            self.display_save_cancel.setEnabled(False)
            self.statusBar().showMessage(f'{self.export_label}の保存取消を待っています。')

    def display_export_finished(self):
        worker=self.display_export
        if worker is None:return
        self.display_export=None
        result=worker.result or dict(status='failed',reason='unexpected')
        on_success=self.export_on_success
        self.last_export_summary=result.get('summary')
        self.export_on_success=None
        worker.deleteLater()
        self.display_save_cancel.hide()
        self.display_save.setText('観測ログを保存…')
        self.history_update_state()
        if self.close_after_display_export:
            self.close()
            return
        if result['status']=='saved':
            if on_success:on_success()
            else:self.statusBar().showMessage(f'{self.export_label}を保存しました。')
        elif result['status']=='cancelled':self.statusBar().showMessage(f'{self.export_label}の保存を取り消しました。')
        else:
            message=('観測出力は64MiB以内にしてください。' if result.get('reason')=='limit' else
                     '入力データ・保存先・空き容量・アクセス権を確認してください。保存を完了できませんでした。')
            QMessageBox.critical(self,'ファイルを保存できません',message)

    def populate_processes(self):
        if self.offline:
            self.process.clear()
            self.process.addItem('保存ログの再解析（取得しません）', None)
            return
        selected = self.process.currentData()
        self.process.clear()
        self.process.addItem('手動指定（接続先は設定から入力）', None)
        for pid, name in list_processes():
            self.process.addItem(f'{name} (PID {pid})', pid)
        if selected is not None:
            idx = self.process.findData(selected)
            if idx >= 0:
                self.process.setCurrentIndex(idx)

    def show_connections(self, endpoints):
        self.connections_table.setRowCount(len(endpoints))
        for row, e in enumerate(endpoints):
            values = [str(e.pid), f'{e.local_ip}:{e.local_port}', e.remote_ip,
                      str(e.remote_port), e.status]
            for col, val in enumerate(values):
                self.connections_table.setItem(row, col, QTableWidgetItem(val))

    def poll_connections(self):
        if self.receiver:
            if self.session_log and self.session_log.error and not self.log_error_reported:
                self.log_error_reported = True
                self.show_capture_status(self.session_log.error)
            try:
                self.receiver.check_health()
            except RuntimeError as exc:
                self.stop()
                self.capture_state_label.setText('取得エラー（診断を確認）')
                self.capture_diagnostics.setPlainText(str(exc))
                self.show_capture_status(str(exc))
                return
            try:
                self.receiver.refresh_connections()
            except Exception as exc:
                self.show_capture_status(f'Process discovery error: {exc}')
            stats = self.receiver.diagnostics()
            self.capture_state_label.setText('観測中' if stats['ready'] else '開始待ち')
            error_count = stats.get('framing_errors', 0) + stats.get('tcp_errors', 0) + self.world.issue_count
            self.diagnostics_button.setText(f'診断 ({error_count})' if error_count else '診断')
            self.capture_diagnostics.setPlainText(
                f'Npcap={"ready" if stats["ready"] else "opening"} | TCP seen={stats.get("observed_tcp", 0)} | '
                f'tracked={stats["tracked"]} | matched={stats.get("matched_segments", 0)} | '
                f'payload={stats.get("matched_payload_bytes", 0)} B | packets={stats.get("framed_packets", 0)} | '
                f'RECV={stats.get("recv_packets", 0)} SEND={stats.get("send_packets", 0)} | '
                f'HTTP PASS={stats.get("passed_http_connections", 0)} | '
                f'waiting SYN={stats.get("waiting_syn_segments", 0)} | framing errors={stats.get("framing_errors", 0)} | '
                f'padding ignored={stats.get("ignored_padding_bytes", 0)} B')

    def start(self):
        if self.workspace_closing or self.offline or self.database_failed or self.bridge.snapshot()["overflowed"]:
            return
        try:
            definitions = load_lengths(self.path.text())
            overlay = self._load_optional_overlay()
            if overlay is not None:
                from parser.packet_overlay import merge_lengths
                definitions = merge_lengths(definitions, overlay)
            port = int(self.port.text()) if self.process.currentData() is None and self.port.text().strip() else None
            if port is not None and not 1 <= port <= 65535:
                raise ValueError('Invalid TCP port')
            if (self.capture_send.isChecked() and self.process.currentData() is None
                    and not self.ip.text().strip() and port is None):
                raise ValueError('対象EXEを選択するか、設定で手動接続先を指定してください。')
            self.capture_state_label.setText('開始待ち')
            self.diagnostics_button.setText('診断')
            self.session_log = SessionLog(self.log_root.text().strip(), definitions,
                                          record_payload=self.record_stream.isChecked(),
                                          overlay=overlay)
            self.log_error_reported = False
            self.show_capture_status(f'Session log: {self.session_log.path}')
            self.session_log.write('capture_options', packet_db_journal=self.db.journal_mode,
                packet_db_synchronous=self.db.synchronous, packet_db_commit='per_packet',
                packet_db_wal_fallback=self.db.wal_fallback, process_pid=self.process.currentData(),
                include_children=self.children.isChecked(), interface=self.iface.text().strip(),
                capture_send=self.capture_send.isChecked(),
                allow_midstream=self.attach_existing.isChecked(),
                manual_server_ip=self.ip.text().strip() if self.process.currentData() is None else None,
                manual_server_port=port)
            next_session = self.capture_session + 1
            on_packet = lambda event, session=next_session: self.bridge.publish(session,event)
            self.receiver = Receiver(self.ip.text().strip() if self.process.currentData() is None else "",
                                     port if self.process.currentData() is None else None, definitions,
                                     on_packet, self.bridge.status.emit,
                                     self.iface.text().strip(),
                                     self.process.currentData(), self.children.isChecked(),
                                     allow_midstream=self.attach_existing.isChecked(), recorder=self.session_log,
                                     capture_send=self.capture_send.isChecked())
            self.receiver.on_connections = self.bridge.connections.emit
            if self.pipe_enabled.isChecked():
                self.pipe = PipeServer(self.pipe_name.text().strip(), definitions,
                                       on_packet, self.bridge.status.emit)
                self.pipe.start()
            self.receiver.start()
            self.capture_session += 1
            self.world_sources[self.capture_session] = str(self.session_log.path)
            self.world.begin_capture(self.capture_session)
            self.players.begin_capture(self.capture_session)
            self.skills.begin_capture(self.capture_session)
            self.combat.begin_capture(self.capture_session)
            self.dialogues.begin_capture(self.capture_session)
            self.world_notified_issues.clear()
            self.refresh_entity_views()
            if self.presenter:
                self.presenter.reset()
            if self.send_presenter:
                self.send_presenter.reset()
            self.monitor_timer.start()
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.update_capture_controls()
        except Exception as e:
            self.stop()
            self.capture_state_label.setText('開始できません（設定を確認）')
            QMessageBox.critical(self, 'Cannot start capture', str(e))

    def stop(self):
        self._stop_capture(finalize_log=not self.workspace_closing)

    def _stop_capture(self,*,finalize_log):
        self.monitor_timer.stop()
        if self.pipe:
            self.pipe.stop()
            self.pipe = None
        if self.receiver:
            try:
                self.receiver.stop()
            except Exception as e:
                self.statusBar().showMessage(str(e))
            self.receiver = None
        if self.session_log and finalize_log:
            self.session_log.close()
        self.start_button.setEnabled(not self.workspace_closing and not self.database_failed)
        self.stop_button.setEnabled(False)
        self.capture_state_label.setText('停止中')
        self.update_packet_progress()
        self.update_capture_controls()

    def packet_delivery_overflow(self):
        counts=self.bridge.snapshot()
        if self.session_log:
            self.session_log.write('packet_delivery_overflow',counts_at_stop=counts)
        self.show_capture_status('GUI処理待ちが上限に達したため取得を停止しました。受付できなかったパケットがあります。診断を確認してください。')
        self.stop()

    def packet_progress(self):
        return dict(self.bridge.snapshot(),gui_received=self.packet_gui_received,processed=self.packet_processed,
                    db_confirmed=self.packet_db_confirmed,db_unconfirmed=self.packet_db_unconfirmed,
                    database_failed=self.database_failed)

    def update_packet_progress(self):
        counts=self.packet_progress()
        self.packet_progress_label.setText(f'この画面: 取得側発行 {counts["published"]} / GUI未受付 {counts["awaiting_gui"]} / '
            f'GUI受付 {counts["gui_received"]} / 処理完了 {counts["processed"]} / '
            f'DB保存確認 {counts["db_confirmed"]} / DB保存未確認 {counts["db_unconfirmed"]} / '
            f'GUI未受付RAW {counts["pending_bytes"]} B / 受付拒否 {counts["rejected"]} '
            f'（終了受付停止後 {counts["shutdown_rejected"]}）')
        if counts['overflowed']:
            self.capture_state_label.setText(f'GUI待機上限で停止 / 受付拒否 {counts["rejected"]}件（取得不完全）')
            self.diagnostics_button.setText('診断（取得不完全）')
            self.start_button.setEnabled(False)
        if self.database_failed:
            self.capture_state_label.setText(f'DB保存エラーで停止 / 保存未確認 {self.packet_db_unconfirmed}件')
            self.diagnostics_button.setText('診断（DB保存エラー）')
            self.start_button.setEnabled(False)

    def add_packet(self, event):
        if self.workspace_closed:
            return
        session=self.capture_session
        if isinstance(event,PacketDelivery):
            self.bridge.accept(event)
            session,event=event.session,event.event
        elif isinstance(event,tuple):
            session,event=event
        self.packet_gui_received+=1
        rowid=None
        if self.database_failed:
            self.packet_db_unconfirmed+=1
        else:
            try:
                rowid=self.db.add(event)
                self.packet_db_confirmed+=1
            except (sqlite3.Error,OSError) as exc:
                self.packet_db_unconfirmed+=1
                self.database_failed=True
                if self.session_log:
                    code=getattr(exc,'sqlite_errorcode',None)
                    self.session_log.write('packet_database_error',error_type=type(exc).__name__,
                        sqlite_errorcode=code if type(code) is int else None,
                        capture_session=session,packet_index=self.event_origin+len(self.events),
                        counts_at_error=self.packet_progress())
                self.show_capture_status('DB保存を確認できないため観測を停止します。診断の未確認件数を確認してください。')
                self.stop()
        try:
            self._apply_packet(event,session,rowid=rowid)
            self.packet_processed+=1
        finally:
            self.update_packet_progress()

    def _apply_packet(self,event,session,rowid=None):
        if len(self.packet_rowids) != len(self.events):
            # Test seeding may fill events without rowids; treat gaps as unsaved.
            self.packet_rowids.extend([None]*(len(self.events)-len(self.packet_rowids)))
        index = self.event_origin + len(self.events)
        self.events.append(event)
        self.display_sessions.append(session)
        self.packet_rowids.append(rowid)
        previous_issues = self.world.issue_count
        self.world.apply(event, session=session, packet_index=index)
        tags = observation_tags(event, self.world, session)
        self.observation_tags.append(tags)
        self.mob_spawns.apply(event, session=session, packet_index=index)
        self.shops.apply(event, session=session, packet_index=index)
        self.barters.apply(event, session=session, packet_index=index)
        self.combat.apply(event, session=session, packet_index=index)
        self.skills.apply(event, session=session, packet_index=index)
        player_observation = self.players.apply(event, session=session, packet_index=index)
        self.dialogues.apply(event, session=session, packet_index=index, player_observation=player_observation)
        if self.world.issue_count != previous_issues:
            for issue in list(self.world.issues)[-(self.world.issue_count - previous_issues):]:
                if self.session_log:
                    self.session_log.write('world_observation_error', **issue)
                identity = (issue['packet_id'], issue['message'])
                if identity not in self.world_notified_issues:
                    self.world_notified_issues.add(identity)
                    self.show_capture_status(f'Entity observation failed: 0x{issue["packet_id"]:04X}: {issue["message"]}')
        renderer = self.presenter if event.direction == 'RECV' else self.send_presenter
        for other in (self.presenter, self.send_presenter):
            if other is not None and other is not renderer:
                other.observe(event)
        result = (renderer.decode(event, self.render_timestamps) if renderer
                  else DisplayResult('', '', 'unmapped'))
        self.display_results.append(result)
        if not self.history_view_stale and not self.history_tasks.running("view") and self.matches(event):
            self.packet_indices.append(index)
            pager=self.packet_pager
            last=(len(self.packet_indices)-1)//DISPLAY_LIMIT
            if pager.follow_latest:
                if pager.page!=last:
                    pager.page=last
                    self.render_packet_page()
                else:
                    self.insert_packet_row(index)
            pager._update()
        self._maybe_evict_memory_events()
        self._refresh_event_counter()
        if not self.history_view_stale and not self.history_tasks.running("view") and self.display_visible(event, result, tags):
            self.append_display_text(result.text)

    def _refresh_event_counter(self):
        retained=len(self.events)
        logical=self.event_origin+retained
        if self.event_origin:
            self.counter.setText(f'{logical} 件（メモリ {retained} / 退避 {self.event_origin}）')
        else:
            self.counter.setText(f'{logical} 件')

    def _maybe_evict_memory_events(self):
        """Drop oldest in-memory packets only after DB confirmation. Never drop unsaved."""
        limit=self.memory_event_limit
        if type(limit) is not int or limit < 1:
            return
        retained=len(self.events)
        if (retained <= limit or self.database_failed or self.history_tasks.busy
                or len(self.packet_rowids) != retained):
            return
        drop=retained-limit
        while drop > 0 and self.packet_rowids[drop-1] is None:
            drop -= 1
        if drop <= 0:
            return
        for offset in range(drop):
            rowid=self.packet_rowids[offset]
            if rowid is None:
                return
            self.evicted_rowids[self.event_origin+offset]=rowid
        trim_parallel(
            (self.events,self.display_results,self.display_sessions,self.observation_tags,self.packet_rowids),
            drop)
        self.event_origin += drop
        self.packet_indices[:] = [index for index in self.packet_indices if index >= self.event_origin]
        if not self.history_view_stale and not self.history_tasks.running('view'):
            self.packet_pager.set_rows(self.packet_indices,'packets')
            self.render_packet_page()
        self.show_capture_status(
            f'メモリ履歴を {drop} 件退避しました（累計 {self.event_origin}）。DB保存済み根拠へ移動できます。')

    def _show_evicted_packet(self, logical):
        rowid=self.evicted_rowids.get(logical)
        if rowid is None:
            self.show_capture_status(f'Packet #{logical} はメモリ退避済みですが DB 行を特定できません。')
            return
        try:
            event=self.db.get(rowid)
        except (KeyError, sqlite3.Error, OSError, ValueError) as exc:
            self.show_capture_status(f'Packet #{logical} のDB読込に失敗しました: {exc}')
            return
        renderer=self.presenter if event.direction=='RECV' else self.send_presenter
        decoded=(renderer.decode(event,self.render_timestamps) if renderer
                 else DisplayResult('','','unmapped'))
        self.table.clearSelection()
        self._fill_packet_detail(event,decoded,prefix=f'退避済み Packet #{logical}（DB id={rowid}）\n')
        self.show_capture_status(f'Packet #{logical} はメモリ退避済みのため DB から表示しています。')

    def selected_packet_index(self):
        item=self.table.item(self.table.currentRow(),0)
        index=item.data(Qt.UserRole) if item is not None else None
        if type(index) is not int:
            return None
        try:
            physical_index(index,self.event_origin)
        except ValueError:
            return None
        if not self.event_origin <= index < self.event_origin+len(self.events):
            return None
        return index

    def insert_packet_row(self,index):
        slot=physical_index(index,self.event_origin)
        event=self.events[slot];result=self.display_results[slot]
        row=self.table.rowCount()
        self.table.insertRow(row)
        values=[datetime.fromtimestamp(event.timestamp).strftime('%H:%M:%S.%f')[:-3],
                event.direction,f'0x{event.packet_id:04X}',str(len(event.raw)),event.source,
                result.text.replace('\n',' ')[:512]]
        for col,value in enumerate(values):
            item=QTableWidgetItem(value);item.setData(Qt.UserRole,index)
            self.table.setItem(row,col,item)

    def render_packet_page(self):
        selected=self.selected_packet_index()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.table.clearSelection()
            self.hex.clear()
            for index in self.packet_pager.visible():self.insert_packet_row(index)
            if selected in self.packet_pager.visible():
                self.table.selectRow(self.packet_pager.visible().index(selected))
        finally:self.table.blockSignals(False)
        self.sync_ignore_selection()
        self.show_selected()

    def matches(self, event):
        value = self.filter.text().strip().lower().removeprefix('0x')
        return not value or value in f'{event.packet_id:04x}'

    def apply_filter(self):
        value = self.filter.text().strip()
        self.filter_notice_label.setText(f'PacketIDで絞り込み中: {value}')
        self.filter_notice.setVisible(bool(value))
        self.rebuild_display_log()

    def _fill_packet_detail(self,event,decoded,prefix=''):
        lines = []
        for offset in range(0, len(event.raw), 16):
            chunk = event.raw[offset:offset + 16]
            hex_part = ' '.join(f'{x:02X}' for x in chunk)
            ascii_part = ''.join(chr(x) if 32 <= x < 127 else '.' for x in chunk)
            lines.append(f'{offset:08X}  {hex_part:<47}  {ascii_part}')
        from parser.packet_overlay import format_indexed_value
        field_lines = []
        for name, value in decoded.fields.items():
            if name.endswith('_index'):
                continue
            label = decoded.fields.get(name + '_index')
            field_lines.append(f'{name}: {format_indexed_value(value, label)}' if label is not None else f'{name}: {value}')
        fields = '\n'.join(field_lines)
        self.hex.setPlainText(
            prefix +
            f'PacketID: 0x{event.packet_id:04X} | {event.connection}\n'
            f'Display: {decoded.status} {decoded.name}\n{decoded.text}\n{fields}\n\n' + '\n'.join(lines))

    def show_selected(self):
        row = self.selected_packet_index()
        if row is None:
            return
        slot=physical_index(row,self.event_origin)
        event = self.events[slot]
        decoded = self.display_results[slot]
        self._fill_packet_detail(event,decoded)

    def closeEvent(self, event):
        self.workspace_closing=True
        self.bridge.seal()
        self.history_tasks.cancel()
        self._stop_capture(finalize_log=False)
        self.start_button.setEnabled(False)
        if self.display_export is not None:
            self.close_after_display_export=True
            self.cancel_display_export()
            event.ignore()
            return
        for window in list(self.offline_windows):
            window.close()
        if self.bridge.snapshot()["awaiting_gui"] or self.offline_windows:
            event.ignore()
            self.statusBar().showMessage('終了処理中：受付済みパケットと子ウィンドウの終了を待っています。')
            QTimer.singleShot(50,self.close)
            return
        self.entity_timer.stop()
        if self.comparison_dialog is not None:
            self.comparison_dialog.close()
        self.settings_dialog.close()
        self.diagnostics_dialog.close()
        self.player_panel.dialog.close()
        self.persist_user_settings()
        if self.session_log:
            self.session_log.write('packet_delivery_shutdown',counts_at_close=self.packet_progress())
            self.session_log.close()
        self.workspace_closed=True
        self.db.close()
        super().closeEvent(event)
