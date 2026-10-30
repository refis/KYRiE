"""Bounded display projections; full model evidence and exports remain unchanged."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QPushButton

DISPLAY_LIMIT=1000


def preview_document(summary,records,limit=DISPLAY_LIMIT):
    if type(limit) is not int or not 1<=limit<=DISPLAY_LIMIT:
        raise ValueError('Invalid preview limit')
    omitted={}
    def project(value,path):
        if isinstance(value,dict):return {key:project(item,path+'.'+str(key)) for key,item in value.items()}
        if isinstance(value,(list,tuple)):
            if len(value)>limit:omitted[path]=omitted.get(path,0)+len(value)-limit
            return [project(item,path+'[]') for item in value[-limit:]]
        return value
    return dict(summary=project(summary,'summary'),observations=project(records,'observations'),
                observation_count=len(records),omitted_from_preview=max(0,len(records)-limit),preview_omissions=omitted)


class IntervalPager(QWidget):
    changed=Signal()
    def __init__(self,parent=None,noun='区間',ordering='系列順'):
        super().__init__(parent)
        self.noun,self.ordering=noun,ordering
        self.rows=[];self.identity=None;self.page=0;self.follow_latest=True
        layout=QHBoxLayout(self)
        self.previous=QPushButton('前の1000件')
        self.next=QPushButton('次の1000件')
        self.caption=QLabel(self.noun+'なし')
        layout.addWidget(self.previous);layout.addWidget(self.caption,1);layout.addWidget(self.next)
        self.previous.clicked.connect(lambda:self.move(-1));self.next.clicked.connect(lambda:self.move(1))
        self._update()

    def _update(self):
        count=len(self.rows);pages=max(1,(count+DISPLAY_LIMIT-1)//DISPLAY_LIMIT)
        self.previous.setEnabled(bool(count and self.page>0))
        self.next.setEnabled(bool(count and self.page<pages-1))
        self.caption.setText(f'{self.noun} {count}件 / {self.page+1}/{pages}ページ（最大{DISPLAY_LIMIT}件/ページ、{self.ordering}）' if count else self.noun+'なし')

    def clear(self):
        self.rows=[];self._update();self.changed.emit()

    def set_rows(self,rows,identity):
        if identity!=self.identity:self.follow_latest=True
        self.rows=rows;self.identity=identity
        last=max(0,(len(rows)-1)//DISPLAY_LIMIT)
        self.page=last if self.follow_latest else min(self.page,last)
        self._update();self.changed.emit()

    def move(self,delta):
        if not self.rows:return
        last=(len(self.rows)-1)//DISPLAY_LIMIT
        self.page=max(0,min(last,self.page+delta));self.follow_latest=self.page==last
        self._update();self.changed.emit()

    def visible(self):
        start=self.page*DISPLAY_LIMIT
        return self.rows[start:start+DISPLAY_LIMIT]
