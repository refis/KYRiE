"""Edit one packet's structure overlay from the packet-detail view."""
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QFileDialog, QAbstractItemView,
)

from parser.display import TYPES
from parser.packet_overlay import (
    INDEX_TAGS, OverlayError, build_packet_entry, fields_from_display_rule,
    find_overlay_packet, length_check, load_overlay, save_overlay, upsert_overlay_packet,
)

FIELD_TYPES = (*TYPES.keys(), 'string', 'bytes')
INDEX_CHOICES = ('', *sorted(INDEX_TAGS))


class OverlayEditorDialog(QDialog):
    def __init__(self, packet_id, raw_length, seed_entry=None, display_rule=None,
                 overlay_path='', parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'構造オーバーレイ — 0x{packet_id:04X}')
        self.resize(720, 480)
        self.packet_id = packet_id
        self.raw_length = raw_length
        self.overlay_path = overlay_path or ''
        self._result_path = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            '選択パケットの長さとフィールドをオーバーレイへ明示保存します。\n'
            '未知ID後の境界再同期はしません。indexは表示注釈のみです。'))

        form = QFormLayout()
        self.name = QLineEdit()
        self.length = QSpinBox()
        self.length.setRange(-1, 65535)
        self.length.setSpecialValueText('可変(-1)')
        # QSpinBox special value uses minimum; keep -1 as minimum.
        self.length.setMinimum(-1)
        self.template = QLineEdit()
        self.min_length = QSpinBox()
        self.min_length.setRange(2, 65535)
        form.addRow('名前', self.name)
        form.addRow('長さ', self.length)
        form.addRow('min_length', self.min_length)
        form.addRow('template', self.template)
        layout.addLayout(form)

        self.length_notes = QLabel()
        self.length_notes.setWordWrap(True)
        layout.addWidget(self.length_notes)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['name', 'offset', 'type', 'length', 'index'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        row_actions = QHBoxLayout()
        add = QPushButton('フィールド追加')
        remove = QPushButton('選択行を削除')
        check = QPushButton('長さを確認')
        add.clicked.connect(self.add_field_row)
        remove.clicked.connect(self.remove_selected_row)
        check.clicked.connect(self.refresh_length_notes)
        row_actions.addWidget(add)
        row_actions.addWidget(remove)
        row_actions.addWidget(check)
        row_actions.addStretch(1)
        layout.addLayout(row_actions)

        path_row = QHBoxLayout()
        self.path = QLineEdit(self.overlay_path)
        browse = QPushButton('保存先…')
        browse.clicked.connect(self.browse_path)
        path_row.addWidget(QLabel('オーバーレイJSON'))
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存して再解析')
        buttons.button(QDialogButtonBox.Cancel).setText('キャンセル')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._seed(seed_entry, display_rule)
        self.length.valueChanged.connect(self.refresh_length_notes)
        self.refresh_length_notes()

    def _seed(self, seed_entry, display_rule):
        entry = seed_entry
        if entry is None and display_rule is not None:
            entry = dict(
                id=f'{self.packet_id:04X}',
                length=self.raw_length if self.raw_length >= 2 else -1,
                name=display_rule.get('name') or f'overlay_{self.packet_id:04X}',
                fields=fields_from_display_rule(display_rule),
                template=display_rule.get('template') or f'@overlay_packet 0x{self.packet_id:04X};',
                min_length=display_rule.get('min_length', 2),
            )
        if entry is None:
            entry = dict(
                id=f'{self.packet_id:04X}',
                length=self.raw_length if self.raw_length >= 2 else -1,
                name=f'overlay_{self.packet_id:04X}',
                fields={},
                template=f'@overlay_packet 0x{self.packet_id:04X};',
                min_length=2,
            )
        self.name.setText(entry.get('name') or '')
        self.length.setValue(entry.get('length', -1))
        self.template.setText(entry.get('template') or f'@overlay_packet 0x{self.packet_id:04X};')
        self.min_length.setValue(entry.get('min_length', 2))
        for name, spec in (entry.get('fields') or {}).items():
            self.add_field_row(name, spec)

    def add_field_row(self, name='', spec=None):
        if not isinstance(name, str):
            name, spec = '', None
        spec = spec or {'offset': 2, 'type': 'u32'}
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name if isinstance(name, str) else ''))
        offset = QSpinBox()
        offset.setRange(0, 65535)
        offset.setValue(int(spec.get('offset', 2)))
        offset.valueChanged.connect(self.refresh_length_notes)
        self.table.setCellWidget(row, 1, offset)
        kind = QComboBox()
        kind.addItems(FIELD_TYPES)
        type_name = spec.get('type', 'u32')
        if type_name in FIELD_TYPES:
            kind.setCurrentText(type_name)
        kind.currentTextChanged.connect(self.refresh_length_notes)
        self.table.setCellWidget(row, 2, kind)
        length = QSpinBox()
        length.setRange(0, 65535)
        length.setSpecialValueText('（自動／末尾）')
        length.setValue(int(spec['length']) if 'length' in spec else 0)
        length.valueChanged.connect(self.refresh_length_notes)
        self.table.setCellWidget(row, 3, length)
        index = QComboBox()
        index.addItems(INDEX_CHOICES)
        tag = spec.get('index', '')
        if tag in INDEX_CHOICES:
            index.setCurrentText(tag)
        self.table.setCellWidget(row, 4, index)

    def remove_selected_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.refresh_length_notes()

    def browse_path(self):
        start = self.path.text().strip() or str(Path.cwd() / 'config' / 'packet_overlay.json')
        chosen, _ = QFileDialog.getSaveFileName(self, 'オーバーレイJSONの保存先', start, 'JSON (*.json)')
        if chosen:
            self.path.setText(chosen)

    def collected_fields(self):
        fields = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            name = (item.text() if item else '').strip()
            if not name:
                raise OverlayError(f'行{row + 1}: フィールド名が空です')
            if name in fields:
                raise OverlayError(f'重複フィールド名: {name}')
            offset = self.table.cellWidget(row, 1).value()
            kind = self.table.cellWidget(row, 2).currentText()
            length_value = self.table.cellWidget(row, 3).value()
            index = self.table.cellWidget(row, 4).currentText().strip()
            spec = dict(offset=offset, type=kind)
            if kind in ('string', 'bytes') and length_value > 0:
                spec['length'] = length_value
            elif kind not in ('string', 'bytes') and length_value > 0:
                raise OverlayError(f'{name}: 整数型にlengthは指定できません')
            if index:
                spec['index'] = index
            fields[name] = spec
        return fields

    def build_entry(self):
        fields = self.collected_fields()
        return build_packet_entry(
            self.packet_id,
            self.length.value(),
            self.name.text().strip(),
            fields,
            template=self.template.text(),
            min_length=self.min_length.value(),
        )

    def refresh_length_notes(self, *_args):
        try:
            fields = self.collected_fields()
            notes = length_check(self.raw_length, self.length.value(), fields)
            self.length_notes.setText(' / '.join(notes))
        except (OverlayError, ValueError, TypeError, AttributeError) as exc:
            self.length_notes.setText(f'長さ確認: {exc}')

    def saved_path(self):
        return self._result_path

    def accept(self):
        try:
            entry = self.build_entry()
            path = self.path.text().strip()
            if not path:
                raise OverlayError('保存先オーバーレイJSONを指定してください')
            existing = None
            target = Path(path)
            if target.is_file():
                existing = load_overlay(target)
            document = upsert_overlay_packet(existing, entry)
            save_overlay(target, document)
            self._result_path = str(target.resolve())
        except (OverlayError, OSError, ValueError) as exc:
            QMessageBox.warning(self, 'オーバーレイを保存できません', str(exc))
            return
        super().accept()
