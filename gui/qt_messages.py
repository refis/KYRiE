"""Qt message helpers that stay non-blocking under offscreen CI."""
import os

from PySide6.QtWidgets import QMessageBox


def warning(parent, title, text):
    """Show a warning dialog, or no-op when QT_QPA_PLATFORM=offscreen.

    Modal QMessageBox blocks forever without a display; generate/load/save
    failure paths must not hang Actions (see hang since run #135 / #114).
    """
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        return
    QMessageBox.warning(parent, title, text)
