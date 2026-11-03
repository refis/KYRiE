"""Explicit manual settings; the observation candidate remains unchanged."""
import json
import os
import tempfile
from storage.observation_export import validate_export_destination
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QFormLayout, QWidget,
    QScrollArea, QLineEdit, QComboBox, QCheckBox, QPushButton, QFileDialog, QMessageBox, QPlainTextEdit)
from reconstruction.mob_skill_export import (COLUMNS, MANUAL_CHOICES, configure_candidate,
    DEFAULT_PROFILE, STATUS_CONDITIONS, STATUS_VALUES, load_configured, MAX_CONFIGURED_BYTES,
    CONFIGURED_PROFILE, render_configured, format_observation_evidence)


class MobSkillEditor(QDialog):
    def __init__(self, candidate, source_sessions, parent=None):
        super().__init__(parent)
        self.candidate, self.source_sessions = deepcopy(candidate), deepcopy(source_sessions)
        self.setWindowTitle('Auriga MOBスキル設定の編集')
        self.resize(720, 800)
        layout = QVBoxLayout(self)
        note = QLabel('未知値は空欄です。全列を確認して入力してください。\n'
                      'RATEは万分率、時間はms。条件は手動指定。\n'
                      'VAL1〜6は符号付き32bit整数、またはカンマ・空白・//なしの64文字以内の文字列。\n'
                      'JSON保存／根拠コメント付きDB行出力に対応。観測値は変更しません。\n'
                      '根拠は画面を開いた時点で固定。追加観測を使う場合は開き直してください。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setPlainText(format_observation_evidence(self.candidate))
        self.evidence.setMinimumHeight(140)
        self.evidence.setMaximumHeight(220)
        layout.addWidget(self.evidence)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        self.fields = {}
        for key in COLUMNS:
            value = candidate['db_fields'][key]
            if key in MANUAL_CHOICES:
                widget = QComboBox()
                widget.addItem('未指定', '')
                for choice in MANUAL_CHOICES[key]:
                    widget.addItem(choice, choice)
                if value is not None:
                    widget.setCurrentIndex(max(0, widget.findData(str(value))))
            else:
                widget = QLineEdit('' if value is None else str(value))
                widget.setMaxLength(256 if key == 'NAME' else 64)
                if key == 'NAME':
                    widget.setToolTip('モンスター名＠スキル名。日本語可。カンマ・改行・//・clearは禁止。')
                elif key.startswith('VAL'):
                    widget.setPlaceholderText('整数または文字列トークン')
                    widget.setToolTip('符号付き32bit整数、またはカンマ・空白・//を含まない64文字以内。観測からは補完しない。')
            self.fields[key] = widget
            form.addRow(key, widget)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.condition_note = QLabel()
        self.condition_note.setWordWrap(True)
        layout.addWidget(self.condition_note)
        self.fields['CONDITION'].currentIndexChanged.connect(self.condition_changed)
        self.condition_changed()
        self.confirmed = QCheckBox('対象Auriga DBのID・仕様と全設定値を確認した')
        layout.addWidget(self.confirmed)
        for widget in self.fields.values():
            signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.textChanged
            signal.connect(self.invalidate_confirmation)
        load_button = QPushButton('保存した設定JSONを読み込む…')
        load_button.clicked.connect(self.load)
        layout.addWidget(load_button)
        preview_button = QPushButton('確認済みDB行と根拠を表示')
        preview_button.clicked.connect(self.generate)
        layout.addWidget(preview_button)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(100)
        layout.addWidget(self.preview)
        self.confirmed.toggled.connect(self.clear_preview)
        button = QPushButton('設定・DB行・観測根拠を保存…')
        button.clicked.connect(self.save)
        layout.addWidget(button)

    def clear_preview(self, *args):
        self.preview.clear()

    def invalidate_confirmation(self, *args):
        self.confirmed.setChecked(False)
        self.clear_preview()

    def generate(self):
        try:
            self.preview.setPlainText(render_configured(self.document()))
        except (ValueError, OSError) as exc:
            self.clear_preview()
            QMessageBox.warning(self, 'DB行を表示できません', str(exc))

    def condition_changed(self):
        condition = self.fields['CONDITION'].currentData()
        status = condition in STATUS_CONDITIONS
        hint = ('状態名: ' + ', '.join(STATUS_VALUES) if status else
                '条件値: 符号付き16bit整数（alwaysは0）。割合・個数・ID等は対象DB仕様で確認。')
        self.condition_note.setText(hint)
        self.fields['CONDITION_VALUE'].setPlaceholderText('状態名を入力' if status else '整数を入力')

    def document(self):
        fields = {key: widget.currentData() if isinstance(widget, QComboBox) else widget.text()
                  for key, widget in self.fields.items()}
        return configure_candidate(self.candidate, fields, confirmed=self.confirmed.isChecked(),
                                   source_sessions=self.source_sessions)

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, '同じ観測根拠の設定を再開', '', 'JSON (*.json)')
        if not path:
            return
        try:
            document = load_configured(path, self.candidate, self.source_sessions)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '設定を読み込めません', str(exc))
            return
        for key, value in document['db_fields'].items():
            widget = self.fields[key]
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(str(value)))
            else:
                widget.setText(str(value))
        self.confirmed.setChecked(False)

    def save(self):
        temporary = None
        try:
            document = self.document()
            text = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
            if len(text.encode('utf-8')) > MAX_CONFIGURED_BYTES:
                raise ValueError('設定JSONは8MiB以内にしてください。')
            path, _ = QFileDialog.getSaveFileName(self, '確認済み設定を保存',
                                                'mob-skill-configured.json',
                                                'JSON (*.json);;Auriga DB text (*.txt)')
            if not path:
                return
            protected = {Path(source).resolve() for source in self.source_sessions.values() if source}
            protected.add(DEFAULT_PROFILE.resolve())
            protected.add(CONFIGURED_PROFILE.resolve())
            if Path(path).resolve() in protected:
                raise ValueError('元ログ・生成書式へ上書きできません。')
            validate_export_destination(path, protected)
            if Path(path).suffix.lower() == '.txt':
                text = render_configured(document)
            elif Path(path).suffix.lower() != '.json':
                raise ValueError('保存形式は.jsonまたは.txtを指定してください。')
            target = Path(path)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                             dir=target.parent, prefix=target.name + '.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, target)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '設定を保存できません', str(exc))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
