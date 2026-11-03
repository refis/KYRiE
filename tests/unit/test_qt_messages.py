"""Offscreen warning helper must not open a blocking modal."""
import os
import unittest
from unittest.mock import patch


class QtMessagesTests(unittest.TestCase):
    def test_warning_is_noop_under_offscreen(self):
        from gui.qt_messages import warning
        previous = os.environ.get('QT_QPA_PLATFORM')
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        try:
            with patch('gui.qt_messages.QMessageBox.warning') as modal:
                warning(None, 'title', 'body')
            modal.assert_not_called()
        finally:
            if previous is None:
                os.environ.pop('QT_QPA_PLATFORM', None)
            else:
                os.environ['QT_QPA_PLATFORM'] = previous

    def test_warning_forwards_when_not_offscreen(self):
        from gui.qt_messages import warning
        previous = os.environ.get('QT_QPA_PLATFORM')
        os.environ.pop('QT_QPA_PLATFORM', None)
        try:
            with patch('gui.qt_messages.QMessageBox.warning') as modal:
                warning('parent', 'title', 'body')
            modal.assert_called_once_with('parent', 'title', 'body')
        finally:
            if previous is None:
                os.environ.pop('QT_QPA_PLATFORM', None)
            else:
                os.environ['QT_QPA_PLATFORM'] = previous
