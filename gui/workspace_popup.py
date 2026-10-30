"""Move an existing comparison page without copying its state or observation store."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout


class WorkspacePopup(QDialog):
    def __init__(self, owner, tabs, page, title):
        super().__init__(owner)
        self.tabs,self.page,self.title=tabs,page,title
        self.home_index=tabs.indexOf(page)
        self.path=owner.path
        self.setWindowTitle(title+' — KYRiE')
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint,True)
        self.resize(1180,800)
        self.content=QVBoxLayout(self)

    def open_page(self):
        index=self.tabs.indexOf(self.page)
        if index>=0:
            self.home_index=index
            self.tabs.removeTab(index)
            self.content.addWidget(self.page)
        button=getattr(self.page,'popout_button',None)
        if button is not None:button.setText('主画面へ戻す')
        self.page.show()

    def closeEvent(self,event):
        if self.tabs.indexOf(self.page)<0:
            self.content.removeWidget(self.page)
            index=self.tabs.insertTab(min(self.home_index,self.tabs.count()),self.page,self.title)
            self.tabs.setCurrentIndex(index)
        button=getattr(self.page,'popout_button',None)
        if button is not None:button.setText('別ウィンドウ…')
        super().closeEvent(event)
