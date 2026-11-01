"""Explicit project log list edits: add / remove / reorder / content replace."""
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
                               QTableWidgetItem, QAbstractItemView, QPushButton, QFileDialog, QMessageBox)

from storage.project import (project_as_schema2, add_project_source, remove_project_source,
                             reorder_project_sources, replace_project_source_content, save_edited_project)


class ProjectSourcesDialog(QDialog):
    def __init__(self, document, project_path, parent=None):
        super().__init__(parent)
        self.document = project_as_schema2(document)
        self.project_path = Path(project_path)
        self.content_replaced = False
        self.setWindowTitle('プロジェクトのログ一覧を編集')
        self.resize(920, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            '生ログの追加・削除・並べ替え・内容差替えを行います。保存後はプロジェクトを開き直して再解析してください。'
            'ライブ取得とは混ぜません。差替えは参照修復と異なりハッシュが変わります。'))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['世代', '生ログ', '長さ定義', 'SHA256(先頭8)'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 360)
        self.table.setColumnWidth(2, 280)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for title, callback in [
                ('追加…', self.add_source), ('削除', self.remove_source),
                ('上へ', lambda: self.move_source(-1)), ('下へ', lambda: self.move_source(1)),
                ('内容を差替え…', self.replace_content),
                ('編集したプロジェクトを保存…', self.save), ('閉じる', self.reject)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        rows = self.document['sources']
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (str(row['capture_session']), row['log']['path'], row['definitions']['path'],
                      row['log']['sha256'][:8])
            for column, text in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(text))

    def _selected(self):
        index = self.table.currentRow()
        return index if index >= 0 else None

    def add_source(self):
        log, _ = QFileDialog.getOpenFileName(self, '追加する生ログ', '', 'Capture log (*.jsonl)')
        if not log:
            return
        definitions, _ = QFileDialog.getOpenFileName(
            self, '長さ定義を選択', str(Path(log).parent), 'Packet length (*.txt);;All files (*)')
        if not definitions:
            return
        try:
            self.document = add_project_source(self.document, log, definitions)
            self.refresh()
            self.table.selectRow(len(self.document['sources']) - 1)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '追加できません', str(exc))

    def remove_source(self):
        index = self._selected()
        if index is None:
            return
        try:
            self.document = remove_project_source(self.document, index)
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, '削除できません', str(exc))

    def move_source(self, delta):
        index = self._selected()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self.document['sources']):
            return
        order = list(range(len(self.document['sources'])))
        order[index], order[target] = order[target], order[index]
        try:
            self.document = reorder_project_sources(self.document, order)
            self.content_replaced = True  # session remapped; old evidence invalid
            self.refresh()
            self.table.selectRow(target)
        except ValueError as exc:
            QMessageBox.warning(self, '並べ替えできません', str(exc))

    def replace_content(self):
        index = self._selected()
        if index is None:
            return
        log, _ = QFileDialog.getOpenFileName(self, '差替える生ログ（内容が異なるファイル）', '', 'Capture log (*.jsonl)')
        if not log:
            return
        answer = QMessageBox.question(
            self, '内容差替えの確認',
            '差替え後は保存時ハッシュが変わります。古い解析根拠への移動は無効になり、'
            'プロジェクトを開き直して再解析する必要があります。続けますか？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        definitions = None
        if QMessageBox.question(self, '長さ定義', '長さ定義も差替えますか？',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            definitions, _ = QFileDialog.getOpenFileName(
                self, '差替える長さ定義', str(Path(log).parent), 'Packet length (*.txt);;All files (*)')
            if not definitions:
                return
        try:
            self.document = replace_project_source_content(
                self.document, index, log, definitions_path=definitions)
            self.content_replaced = True
            self.refresh()
            self.table.selectRow(index)
            QMessageBox.information(self, '差替えました',
                                    'ハッシュが更新されました。保存後にプロジェクトを開き直してください。')
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '差替えできません', str(exc))

    def save(self):
        stem = self.project_path.name.removesuffix('.gpa.json')
        path, _ = QFileDialog.getSaveFileName(
            self, '編集した作業プロジェクトを保存',
            str(self.project_path.with_name(stem + '-edited.gpa.json')), 'Project (*.gpa.json)')
        if not path:
            return
        try:
            save_edited_project(path, self.document)
            message = '作業メニューから保存したプロジェクトを開いて再解析してください。'
            if self.content_replaced:
                message = '内容差替えまたは世代の付け替えを含みます。' + message
            QMessageBox.information(self, '編集した作業を保存しました', message)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '保存できません', str(exc))
