"""Editor for observation-log exclusions and optional save skips."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QCheckBox,
                               QDialogButtonBox, QMessageBox)
from parser.ignorepacket import IgnorePacket, packet_flag_entries, HIDE_LOG, SKIP_SAVE


class IgnorePacketDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('ignorepacket — 観測ログ／保存の除外設定')
        self.resize(560, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            '観測ログとそのテキスト保存、および任意でSQLite保存に適用します。\n'
            '意味解析・会話復元は継続します。flag&2でもデコードは止めません。'))
        layout.addWidget(QLabel(
            'PacketID（16進数）。例: 0085 または 0085:1\n'
            'flag 1=ログ非表示、2=SQLite保存しない、3=両方。裸のIDは1扱い。'))
        lines = []
        for packet_id in sorted(settings.ids | settings.skip_save):
            lines.append(f'{packet_id:04X}:{settings.packet_flag(packet_id)}')
        self.ids = QPlainTextEdit('\n'.join(lines))
        layout.addWidget(self.ids)
        self.mob = QCheckBox('MOBのスキル・攻撃を観測ログ非表示')
        self.mob.setChecked(settings.mob_combat)
        layout.addWidget(self.mob)
        layout.addWidget(QLabel('演出を非表示にするNPC（1行1件）\nActorIDは id:42 または id:0x2A、NPC名は name:案内人'))
        self.npcs = QPlainTextEdit('\n'.join([f'id:{v}' for v in sorted(settings.npc_actors)]
                                            + [f'name:{v}' for v in sorted(settings.npc_names)]))
        layout.addWidget(self.npcs)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存して適用')
        buttons.button(QDialogButtonBox.Cancel).setText('キャンセル')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self):
        actors, names = set(), set()
        for row in self.npcs.toPlainText().splitlines():
            row = row.strip()
            if not row:
                continue
            if row.startswith('id:'):
                value = row[3:].strip()
                actor = int(value, 16 if value.lower().startswith('0x') else 10)
                if not 0 <= actor <= 0xffffffff:
                    raise ValueError('ActorIDは0〜4294967295を指定してください。')
                actors.add(actor)
            elif row.startswith('name:') and 0 < len(row[5:].strip()) <= 256:
                names.add(row[5:].strip())
            else:
                raise ValueError('NPCリストは id:ActorID または name:NPC名 の形式にしてください。')
        if len(actors) > 1000 or len(names) > 1000:
            raise ValueError('NPCリストは各1000件以下にしてください。')
        flags = packet_flag_entries(self.ids.toPlainText())
        ids = frozenset(pid for pid, flag in flags.items() if flag & HIDE_LOG)
        skip_save = frozenset(pid for pid, flag in flags.items() if flag & SKIP_SAVE)
        return IgnorePacket(ids, skip_save, self.mob.isChecked(),
                            frozenset(actors), frozenset(names))

    def accept(self):
        try:
            self.settings().save()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '設定を保存できません', str(exc))
            return
        super().accept()
