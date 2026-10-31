import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from storage.database import PacketDatabase


class WindowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from reconstruction.emulator_profiles import set_target
        set_target('auriga')
        self.db = PacketDatabase(':memory:')
        self.log_folder = tempfile.TemporaryDirectory()
        self.settings_folder = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_folder.name) / 'user_settings.json'
        self._settings_patcher = patch('storage.user_settings.DEFAULT_PATH', self.settings_path)
        self._settings_patcher.start()
        try:
            with patch('gui.main_window.PacketDatabase', return_value=self.db), \
                 patch('gui.main_window.list_processes', return_value=[]):
                self.window = MainWindow()
        except Exception:
            self._settings_patcher.stop()
            self.settings_folder.cleanup()
            self.log_folder.cleanup()
            raise
        self.window.log_root.setText(self.log_folder.name)
        self.window.ip.setText('127.0.0.1')

    def tearDown(self):
        from reconstruction.emulator_profiles import set_target
        set_target('auriga')
        try:
            self.window.close()
            self.wait_window_closed()
        finally:
            self._settings_patcher.stop()
            self.log_folder.cleanup()
            self.settings_folder.cleanup()


    def wait_display_export(self, timeout_ms=60000):
        """Wait for the shared export worker. Large MOB/NPC JSON can exceed 5s on CI."""
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtTest import QTest
        elapsed=QElapsedTimer();elapsed.start()
        while self.window.display_export is not None and elapsed.elapsed()<timeout_ms:
            self.app.processEvents();QTest.qWait(1)
        self.assertIsNone(self.window.display_export)


    def wait_window_closed(self, timeout_ms=60000):
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtTest import QTest
        elapsed=QElapsedTimer();elapsed.start()
        while not self.window.workspace_closed and elapsed.elapsed()<timeout_ms:
            self.app.processEvents();QTest.qWait(1)
        self.assertTrue(self.window.workspace_closed)
