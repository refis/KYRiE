"""Paged reference-only map, quest and navigation browser."""
import json
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,
                              QPushButton,QTableWidget,QTableWidgetItem,QPlainTextEdit)
from reconstruction.navigation import lookup_map

HEADERS={
 'maps':['MAP識別子（資料）','TXT名称','ナビ名称候補','ナビ元列（未解釈）'],
 'quests':['QuestID（資料）','名称候補'],
 'npcs':['MAP（資料）','ナビID','列3','列4','名称','内部名（資料）','列7','列8'],
 'mobs':['MAP（資料）','ナビID','列3','列4','名称','内部名（資料）','列7','列8'],
 'links':['MAP（資料）','ナビID','列3','列4','表示名','内部名（資料）','列7','列8','移動先MAP（資料）','列10','列11'],
 'scrolls':['元MAP（資料）','列2','列3','先MAP（資料）','列5','列6'],
 'picknpcs':['MAP（資料）']+['列'+str(i) for i in range(2,13)]}


class ReferenceBrowser(QDialog):
    PAGE_SIZE=100
    def __init__(self,names,navigation,parent=None,*,current_map=None):
        super().__init__(parent)
        self.names,self.navigation=names,navigation
        self.offset=0;self.matches=[]
        self.current_map=current_map
        self.setWindowTitle('MAP・クエスト・ナビゲーション資料')
        self.resize(1050,620)
        layout=QVBoxLayout(self)
        note=QLabel('外部参考資料です。ナビIDはActorIDではありません。数値列の意味・配置・湧き数は未確定です。\n'
                    '観測状態・NPC/MOB配置・クエスト進行条件・復元コードには反映しません。')
        note.setWordWrap(True);layout.addWidget(note)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.kind=QComboBox()
        for title,key in [('MAP名称','maps'),('クエスト名称','quests'),('NPC資料','npcs'),('MOB資料','mobs'),
                          ('移動先資料','links'),('スクロール資料','scrolls'),('選択ワープ資料','picknpcs')]:
            self.kind.addItem(title,key)
        controls.addWidget(self.kind)
        self.query=QLineEdit();self.query.setPlaceholderText('名称・ID・MAPを検索（部分一致）');controls.addWidget(self.query,1)
        self.map_query=QLineEdit();self.map_query.setPlaceholderText('MAP完全一致（gat/rsw可）');controls.addWidget(self.map_query)
        self.current=QPushButton('現在MAP');controls.addWidget(self.current)
        self.current.setEnabled(current_map is not None)
        self.current.clicked.connect(lambda:self.map_query.setText(self.current_map() or ''))
        self.previous=QPushButton('前へ');self.next=QPushButton('次へ');self.count=QLabel()
        for widget in (self.previous,self.next,self.count):controls.addWidget(widget)
        self.table=QTableWidget();self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows);layout.addWidget(self.table,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(110);layout.addWidget(self.details)
        self.kind.currentIndexChanged.connect(self.search)
        self.query.textChanged.connect(self.search);self.map_query.textChanged.connect(self.search)
        self.previous.clicked.connect(lambda:self.page(-1));self.next.clicked.connect(lambda:self.page(1))
        self.table.itemSelectionChanged.connect(self.show_details)
        self.search()

    def rows(self,key):
        if key=='quests':
            return [[int(qid),' / '.join(labels)+('（名称候補）' if len(labels)>1 else '')]
                    for qid,labels in sorted(self.names['tables']['quests'].items(),key=lambda pair:int(pair[0]))]
        if key!='maps':return self.navigation['tables'][key]
        nav={}
        for row in self.navigation['tables']['maps']:nav.setdefault(row[0],[]).append(row)
        txt={key[:-4]:label for key,label in self.names['tables']['maps'].items()}
        return [[key,txt.get(key,''),' / '.join(dict.fromkeys(row[1] for row in nav.get(key,[]))),
                 json.dumps(nav.get(key,[]),ensure_ascii=False)] for key in sorted(txt.keys()|nav.keys())]

    def search(self,*args):
        key=self.kind.currentData();query=self.query.text().strip().casefold()
        self.map_query.setEnabled(key!='quests')
        self.current.setEnabled(key!='quests' and self.current_map is not None)
        map_key=lookup_map(self.map_query.text().strip())
        self.matches=[row for row in self.rows(key)
                      if (not query or any(query in str(value).casefold() for value in row))
                      and (not map_key or key=='quests' or row[0]==map_key)]
        self.offset=0;self.display()

    def page(self,step):
        self.offset=max(0,min(max(0,(len(self.matches)-1)//self.PAGE_SIZE*self.PAGE_SIZE),self.offset+step*self.PAGE_SIZE))
        self.display()

    def display(self):
        key=self.kind.currentData();headers=HEADERS[key]
        self.table.clear();self.table.setColumnCount(len(headers));self.table.setHorizontalHeaderLabels(headers)
        rows=self.matches[self.offset:self.offset+self.PAGE_SIZE];self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.count.setText(f'{len(self.matches)}件 / {self.offset+1 if rows else 0}–{self.offset+len(rows)}')
        self.previous.setEnabled(self.offset>0);self.next.setEnabled(self.offset+self.PAGE_SIZE<len(self.matches))
        self.details.clear()

    def show_details(self):
        index=self.table.currentRow()+self.offset
        row=self.matches[index] if self.table.currentRow()>=0 and index<len(self.matches) else None
        self.details.setPlainText(json.dumps(dict(reference=row,client_names_sha256=self.names['_sha256'],
            navigation_sha256=self.navigation['_sha256']),ensure_ascii=False,indent=2) if row else '')
