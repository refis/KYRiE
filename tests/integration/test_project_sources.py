from pathlib import Path
import struct
from unittest.mock import patch

from gui.project_sources import ProjectSourcesDialog
from parser.display import DEFAULT_PROFILE, DEFAULT_SEND_PROFILE
from reconstruction.auriga import DEFAULT_DIALOGUE_PROFILE
from storage.project import fingerprint, load_project, save_project, verify_project
from storage.session_log import SessionLog
from tests.support.dialogue import packet
from tests.support.qt import WindowTestCase
from PySide6.QtWidgets import QMessageBox


class ProjectSourcesTests(WindowTestCase):
    def test_content_replace_updates_hash_and_requires_reopen_message(self):
        root = Path(self.log_folder.name)
        recording = SessionLog(root, {0xb4: -1}, record_payload=True)
        recording.write('capture_format', transport='tcp_segments', capture_send=False)
        endpoints = ('server', 5121, 'client', 1234)
        recording.write('tcp_segment', endpoints=endpoints, sequence=100, flags=18, data=b'', timestamp=0, direction='RECV')
        recording.write('tcp_segment', endpoints=endpoints, sequence=101, flags=16,
                        data=packet(0xb4, struct.pack('<I', 42) + b'hello\0').raw, timestamp=1, direction='RECV')
        recording.close()
        log = recording.path
        definitions = log.with_name('PacketLength.used.txt')
        project = root / 'work.gpa.json'
        save_project(project, dict(log=log, definitions=definitions, recv=DEFAULT_PROFILE,
            send=DEFAULT_SEND_PROFILE, dialogue=DEFAULT_DIALOGUE_PROFILE),
            dict(filter='', timestamps=False, unmapped=False, tab=0, conversation=-1, merged=False),
            '編集前', fingerprint(log, 1024))
        before = project.read_bytes()
        other = root / 'other.jsonl'
        other.write_text('different-capture\n', encoding='utf-8')
        dialog = ProjectSourcesDialog(load_project(project), project, self.window)
        try:
            self.assertEqual(dialog.document['schema'], 2)
            dialog.table.selectRow(0)
            with patch('gui.project_sources.QFileDialog.getOpenFileName', return_value=(str(other), '')), \
                 patch('gui.project_sources.QMessageBox.question', side_effect=[QMessageBox.Yes, QMessageBox.No]), \
                 patch('gui.project_sources.QMessageBox.information') as info:
                dialog.replace_content()
            info.assert_called()
            self.assertTrue(dialog.content_replaced)
            self.assertNotEqual(dialog.document['sources'][0]['log']['sha256'],
                                load_project(project)['files']['log']['sha256'])
            edited = root / 'edited.gpa.json'
            with patch('gui.project_sources.QFileDialog.getSaveFileName', return_value=(str(edited), '')), \
                 patch('gui.project_sources.QMessageBox.information'):
                dialog.save()
            verify_project(load_project(edited))
            self.assertEqual(project.read_bytes(), before)
        finally:
            dialog.close()
