from pathlib import Path
import struct
from unittest.mock import patch

from gui.project_references import ProjectReferencesDialog
from parser.display import DEFAULT_PROFILE, DEFAULT_SEND_PROFILE
from reconstruction.auriga import DEFAULT_DIALOGUE_PROFILE
from storage.project import fingerprint, load_project, save_project, verify_project, project_references
from tests.support.qt import WindowTestCase
from tests.support.dialogue import packet
from storage.session_log import SessionLog
from PySide6.QtCore import QElapsedTimer
from PySide6.QtTest import QTest


class ProjectReferencesTests(WindowTestCase):
    def test_relocation_rejects_different_content_and_preserves_original_project(self):
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
            '移動前の注記', fingerprint(log, 1024))
        before = project.read_bytes()
        moved = root / 'moved.jsonl'
        moved.write_bytes(log.read_bytes())
        log.unlink()
        dialog = ProjectReferencesDialog(load_project(project), project, self.window)
        try:
            index = next(i for i, (key, _) in enumerate(project_references(dialog.document)) if key == 'log')
            dialog.table.selectRow(index)
            with patch('gui.project_references.QFileDialog.getOpenFileName', return_value=(str(definitions), '')), \
                 patch('gui.project_references.QMessageBox.warning') as warning:
                dialog.choose_reference()
            warning.assert_called_once()
            self.assertEqual(dialog.document['files']['log']['path'], str(log))
            with patch('gui.project_references.QFileDialog.getOpenFileName', return_value=(str(moved), '')):
                dialog.choose_reference()
            repaired = root / 'repaired.gpa.json'
            with patch('gui.project_references.QFileDialog.getSaveFileName', return_value=(str(repaired), '')), \
                 patch('gui.project_references.QMessageBox.information'):
                dialog.save()
            fixed = load_project(repaired)
            verify_project(fixed)
            self.assertEqual(fixed['files']['log']['path'], str(moved))
            self.assertEqual(fixed['note'], '移動前の注記')
            self.assertEqual(project.read_bytes(), before)
            self.assertFalse(self.window.events)
            with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(repaired), '')):
                self.window.open_project()
            restored = self.window.offline_windows[-1]
            try:
                timer = QElapsedTimer()
                timer.start()
                while not restored.save_project_action.isEnabled() and timer.elapsed() < 5000:
                    self.app.processEvents()
                    QTest.qWait(1)
                self.assertTrue(restored.save_project_action.isEnabled())
                self.assertEqual(len(restored.events), 1)
                self.assertEqual(restored.world_sources, {1: str(moved)})
            finally:
                restored.close()
        finally:
            dialog.close()
