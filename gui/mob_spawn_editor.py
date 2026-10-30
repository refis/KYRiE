"""Manual placement settings with the original observation preserved."""
import json
import os
import tempfile
from storage.observation_export import validate_export_destination
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QFileDialog, QMessageBox, QPlainTextEdit, QScrollArea, QWidget)
from reconstruction.mob_spawn_export import (PLACEMENT_FIELDS, DEFAULT_PROFILE,
    CONFIGURED_PROFILE, configure_candidate, load_configured, render_configured)


class MobSpawnEditor(QDialog):
    def __init__(self, candidate, sources, parent=None):
        super().__init__(parent)
        self.candidate, self.sources = deepcopy(candidate), deepcopy(sources)
        self.setWindowTitle('Auriga MOB配置の手動設定')
        self.resize(720, 720)
        layout = QVBoxLayout(self)
        note = QLabel('初回座標・追跡数・観測間隔を設定へ自動代入しません。\n'
                      '位置・範囲は0〜1023、湧き数は1〜1000、時間はms。\n'
                      'eventの空欄は「イベントなし」を明示する設定です。\n'
                      '根拠は画面を開いた時点で固定します。追加観測を使う場合は開き直してください。')
        note.setWordWrap(True)
        layout.addWidget(note)
        form_content = QWidget()
        form = QFormLayout(form_content)
        self.fields = {}
        for key in PLACEMENT_FIELDS:
            value = candidate['placement_fields'][key]
            field = QLineEdit('' if value is None else str(value))
            field.setMaxLength(76)
            self.fields[key] = field
            form.addRow(key, field)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_content)
        form_scroll.setMinimumHeight(160)
        layout.addWidget(form_scroll, 1)
        self.confirmed = QCheckBox('ID・マップ・全配置設定を確認し、event空欄はイベントなしと確認した')
        layout.addWidget(self.confirmed)
        for field in self.fields.values():
            field.textChanged.connect(self.invalidate_confirmation)
        self.confirmed.toggled.connect(self.clear_preview)
        load_button = QPushButton('保存した設定JSONを読み込む…')
        load_button.clicked.connect(self.load)
        layout.addWidget(load_button)
        preview_button = QPushButton('確認済み配置行と根拠を表示')
        preview_button.clicked.connect(self.generate)
        layout.addWidget(preview_button)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(100)
        layout.addWidget(self.preview)
        button = QPushButton('配置行・手動設定・観測根拠をJSON保存…')
        button.clicked.connect(self.save)
        layout.addWidget(button)
        text_button = QPushButton('確認済み配置行を根拠付きテキスト保存…')
        text_button.clicked.connect(lambda: self.save(as_text=True))
        layout.addWidget(text_button)

    def clear_preview(self, *args):
        self.preview.clear()

    def invalidate_confirmation(self, *args):
        self.confirmed.setChecked(False)
        self.clear_preview()

    def generate(self):
        try:
            self.preview.setPlainText(render_configured(self.document(), self.candidate, self.sources))
        except (ValueError, OSError) as exc:
            self.clear_preview()
            QMessageBox.warning(self, '配置を表示できません', str(exc))

    def document(self):
        return configure_candidate(self.candidate, {key: field.text() for key, field in self.fields.items()},
                                   confirmed=self.confirmed.isChecked(), source_sessions=self.sources)

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, '同じ観測のMOB配置設定を再編集', '', 'JSON (*.json)')
        if not path:
            return
        try:
            document = load_configured(path, self.candidate, self.sources)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '配置設定を読み込めません', str(exc))
            return
        for key, field in self.fields.items():
            field.setText(str(document['placement_fields'][key]))
        self.confirmed.setChecked(False)

    def save(self, checked=False, *, as_text=False):
        temporary = None
        try:
            document = self.document()
            text = (render_configured(document, self.candidate, self.sources) if as_text else
                    json.dumps(document, ensure_ascii=False, indent=2) + '\n')
            if len(text.encode('utf-8')) > 8 * 1024 * 1024:
                raise ValueError('設定JSONが8MiBを超えています。')
            path, _ = QFileDialog.getSaveFileName(self, '確認済みMOB配置を保存',
                                                'mob-spawn-configured.txt' if as_text else 'mob-spawn-configured.json',
                                                'Text (*.txt)' if as_text else 'JSON (*.json)')
            if not path:
                return
            protected = {Path(source).resolve() for source in self.sources.values() if source}
            protected.update((DEFAULT_PROFILE.resolve(), CONFIGURED_PROFILE.resolve()))
            if Path(path).resolve() in protected:
                raise ValueError('元ログ・生成書式へ上書きできません。')
            validate_export_destination(path, protected)
            target = Path(path)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                             dir=target.parent, prefix=target.name + '.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, target)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '配置を保存できません', str(exc))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
