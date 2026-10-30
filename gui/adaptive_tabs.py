"""Size detail tabs for the visible page rather than the tallest hidden report."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QTabWidget, QStyle


class CurrentPageTabs(QTabWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda *_:self.updateGeometry())

    def _page_size(self,minimum):
        page=self.currentWidget()
        if page is None:return super().minimumSizeHint() if minimum else super().sizeHint()
        size=page.minimumSizeHint() if minimum else page.sizeHint()
        bar=self.tabBar().minimumSizeHint() if minimum else self.tabBar().sizeHint()
        frame=self.style().pixelMetric(QStyle.PM_DefaultFrameWidth,None,self)*2
        return QSize(max(size.width(),bar.width())+frame,size.height()+bar.height()+frame)

    def minimumSizeHint(self):return self._page_size(True)
    def sizeHint(self):return self._page_size(False)
