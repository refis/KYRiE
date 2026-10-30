"""Explicit reference relocation without accepting changed packet contents."""
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
                               QTableWidgetItem, QAbstractItemView, QPushButton, QFileDialog, QMessageBox)

from storage.project import project_references, relocate_project, save_relocated_project
from reconstruction.emulator_profiles import profile as generation_profile, TARGETS

LABELS = {'log': '生ログ', 'definitions': '長さ定義', 'recv': 'RECV表示', 'send': 'SEND表示', 'dialogue': '会話書式', 'skill_names':'スキル名辞書',
          'skill_units':'ユニット辞書', 'reference_names':'状態・効果辞書', 'client_names':'品名・MAP・クエスト辞書', 'navigation':'ナビゲーション資料'}


class ProjectReferencesDialog(QDialog):
    def __init__(self, document, project_path, parent=None):
        super().__init__(parent)
        self.document, self.project_path = document, Path(project_path)
        self.setWindowTitle('プロジェクトの参照先を修復')
        self.resize(900, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('移動先を選び、保存時と同じ内容のファイルへ再接続します。元のプロジェクトは自動更新しません。'))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['種別', '参照先', '状態'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 620)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for title, callback in [('選択した参照先を変更…', self.choose_reference),
                                ('修復したプロジェクトを保存…', self.save), ('閉じる', self.reject)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self, verified=None):
        refs = list(project_references(self.document))
        self.table.setRowCount(len(refs))
        for row, (key, ref) in enumerate(refs):
            status = '一致確認済み' if row == verified else '未検証' if Path(ref['path']).is_file() else 'ファイルなし'
            for column, text in enumerate((LABELS[key], ref['path'], status)):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def choose_reference(self):
        index = self.table.currentRow()
        if index < 0:
            return
        key, ref = list(project_references(self.document))[index]
        path, _ = QFileDialog.getOpenFileName(self, '同じ内容の移動先ファイルを選択', str(Path(ref['path']).parent), 'All files (*)')
        if not path:
            return
        try:
            if key == 'dialogue':
                allowed = {generation_profile('dialogue.json', name).resolve() for name in TARGETS}
                if Path(path).resolve() not in allowed:
                    raise ValueError('会話書式は現在の同梱ファイルを選択してください。')
            self.document = relocate_project(self.document, {index: path})
            self.refresh(verified=index)
            self.table.selectRow(index)
        except (OSError, ValueError):
            QMessageBox.warning(self, '参照先を変更できません', 'ファイルの内容が保存時と異なるか、読み取れません。')

    def save(self):
        stem = self.project_path.name.removesuffix('.gpa.json')
        path, _ = QFileDialog.getSaveFileName(self, '修復した作業プロジェクトを保存',
                                            str(self.project_path.with_name(stem + '-relinked.gpa.json')),
                                            'Project (*.gpa.json)')
        if not path:
            return
        try:
            save_relocated_project(path, self.document)
            QMessageBox.information(self, '修復した作業を保存しました', '作業メニューから保存したプロジェクトを開いてください。')
        except (OSError, ValueError):
            QMessageBox.warning(self, '保存できません', '全ての参照先の内容・有無と、保存先を確認してください。')
