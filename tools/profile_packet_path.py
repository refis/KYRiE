"""Isolate SQLite persistence and packet-table insertion with temporary synthetic data."""
import argparse
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
from statistics import median
import struct
import sys
import tempfile
from time import perf_counter
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QTableWidget,QTableWidgetItem
from events import PacketEvent
from storage.database import PacketDatabase
from storage.observation_export import save_observations


def packets(count):
    return [PacketEvent(1+index*.001,'RECV',0x7f,struct.pack('<HI',0x7f,index),'SYNTHETIC','synthetic') for index in range(count)]


def profile(count,runs,app):
    events=packets(count);database=[];memory=[];wal=[];table_times=[]
    with tempfile.TemporaryDirectory(prefix='kyrie-db-profile-') as folder:
        for run in range(runs):
            for name,path,output in (('file',Path(folder)/f'{run}.sqlite3',database),('memory',':memory:',memory),('wal',Path(folder)/f'{run}-wal.sqlite3',wal)):
                db=PacketDatabase(path,wal=name=='wal')
                if name=='wal':
                    assert db.journal_mode=='wal' and db.synchronous==2
                started=perf_counter()
                for event in events:db.add(event)
                output.append(round((perf_counter()-started)*1000,3))
                assert db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0]==count
                db.close()
                if name in ('file','wal'):
                    import sqlite3
                    with closing(sqlite3.connect(path)) as verify:
                        assert verify.execute('SELECT COUNT(*) FROM packets').fetchone()[0]==count
            table=QTableWidget(0,6)
            started=perf_counter()
            for index,event in enumerate(events):
                row=table.rowCount();table.insertRow(row)
                values=[datetime.fromtimestamp(event.timestamp).strftime('%H:%M:%S.%f')[:-3],event.direction,
                        f'0x{event.packet_id:04X}',str(len(event.raw)),event.source,'']
                for column,value in enumerate(values):
                    item=QTableWidgetItem(value);item.setData(Qt.UserRole,index);table.setItem(row,column,item)
                table.setRowHidden(row,False)
            app.processEvents();table_times.append(round((perf_counter()-started)*1000,3))
            assert table.rowCount()==count
            table.close();table.deleteLater();app.processEvents()
    return dict(packet_count=count,wal_full_ms=wal,wal_full_median_ms=median(wal),file_db_ms=database,file_db_median_ms=median(database),
                memory_db_ms=memory,memory_db_median_ms=median(memory),
                table_insert_ms=table_times,table_insert_median_ms=median(table_times),rows_verified=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events',type=int,nargs='+',default=[500,2000])
    parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not 1<=args.runs<=3 or len(args.events)>4 or any(not 1<=n<=10000 for n in args.events):
        parser.error('Use 1..3 runs, <=4 sizes of 1..10000 packets')
    app=QApplication.instance() or QApplication([])
    rows=[]
    for count in args.events:
        result=profile(count,args.runs,app);rows.append(result);print(json.dumps(result),flush=True)
    save_observations(args.output,dict(kind='packet_path_profile',python=sys.version,runs=args.runs,
        qt_mode=os.environ.get('QT_QPA_PLATFORM'),source='synthetic',captures_live_traffic=False,
        includes_decoding_or_event_analysis=False,scenarios=rows))


if __name__=='__main__':main()
