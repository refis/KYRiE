"""Measure history reformat/filter callbacks with synthetic prebuilt events."""
import argparse
import os
from time import perf_counter
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from events import PacketEvent
from gui.main_window import MainWindow
from parser.display import DisplayResult
from storage.database import PacketDatabase
from storage.observation_export import save_observations


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    rows=[]
    for count in (10000,50000):
        with patch('gui.main_window.PacketDatabase',side_effect=lambda *a:PacketDatabase(':memory:')),patch('gui.main_window.list_processes',return_value=[]):
            window=MainWindow()
        window.entity_timer.stop()
        window.events[:]=[PacketEvent(index,'RECV',0xb5,b'\xb5\0'+bytes(4),'SYNTHETIC','flow') for index in range(count)]
        window.display_sessions[:]=[0]*count
        window.observation_tags[:]=[{} for _ in range(count)]
        window.display_results[:]=[DisplayResult('test','next;','decoded') for _ in range(count)]
        times=[]
        # A later implementation can complete through timer slices.
        from PySide6.QtCore import QTimer
        heartbeats=[]
        timer=QTimer();timer.setInterval(0);timer.timeout.connect(lambda:heartbeats.append(perf_counter()))
        timer.start()
        for name,action in [('reformat',window.reformat_display),('filter',lambda:window.filter.setText('ffff'))]:
            heartbeats.clear()
            start=perf_counter();action();returned=perf_counter()
            while hasattr(window,'history_tasks') and window.history_tasks.busy:
                app.processEvents()
            end=perf_counter()
            points=[start,*heartbeats,end]
            times.append(dict(operation=name,callback_ms=round((returned-start)*1000,3),
                total_ms=round((end-start)*1000,3),heartbeat_count=len(heartbeats),
                max_heartbeat_gap_ms=round(max(b-a for a,b in zip(points,points[1:]))*1000,3)))
        timer.stop();window.close();app.processEvents()
        rows.append(dict(packet_count=count,operations=times))
    save_observations(args.output,dict(kind='history_update_profile',source='synthetic',
        includes_capture_database_or_semantic_reconstruction=False,scenarios=rows))
    for row in rows:print(row,flush=True)


if __name__=='__main__':main()
