"""Compute dialogue merge reports off the GUI thread; callers discard stale keys."""
from copy import deepcopy

from PySide6.QtCore import QThread, Signal

from reconstruction.branches import build_merged


class MergeWorker(QThread):
    completed = Signal(object, object)  # key, report
    failed = Signal(object, str)  # key, message

    def __init__(self, key, inputs, touch_inferences, parent=None):
        super().__init__(parent)
        self.key = key
        # Deep copy before the worker starts so GUI mutations cannot race build_merged.
        self._inputs = [(ref, deepcopy(item)) for ref, item in inputs]
        self._touch = deepcopy(list(touch_inferences))

    def run(self):
        try:
            report = build_merged(self._inputs, touch_inferences=self._touch)
        except Exception as exc:  # noqa: BLE001 — surface to GUI; do not apply partial merge
            self.failed.emit(self.key, str(exc))
            return
        self.completed.emit(self.key, report)
