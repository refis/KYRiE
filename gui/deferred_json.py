"""Render read-only JSON only when shown or explicitly requested on the GUI thread."""
import json
from PySide6.QtWidgets import QPlainTextEdit


class DeferredJsonView(QPlainTextEdit):
    def __init__(self,parent=None,*,ensure_current=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.ensure_current=ensure_current
        self._materializing=False
        self._key=None
        self._factory=None
        self._dirty=False
        self.materialize_count=0
        self.factory_calls=0

    def set_document(self,key,factory):
        if self._key==key:return
        self._key=key
        self._factory=factory
        self._dirty=True
        if self.isVisible():self.materialize()
        else:super().clear()

    def materialize(self):
        if self._materializing:return
        self._materializing=True
        try:
            if self.ensure_current is not None:self.ensure_current()
            if self._dirty:
                self.factory_calls+=1
                text=json.dumps(self._factory(),ensure_ascii=False,indent=2)
                super().setPlainText(text)
                self._dirty=False
                self.materialize_count+=1
        finally:
            self._materializing=False

    def toPlainText(self):
        self.materialize()
        return super().toPlainText()

    def showEvent(self,event):
        self.materialize()
        super().showEvent(event)

    def clear(self):
        self._key=None
        self._factory=None
        self._dirty=False
        super().clear()
