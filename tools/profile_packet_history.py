"""Compare widget projection growth with synthetic, already decoded history."""
import argparse
import gc
import os
import tracemalloc
from time import perf_counter
from types import SimpleNamespace
import psutil
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QTableWidget,QPlainTextEdit
from events import PacketEvent
from parser.display import DisplayResult
from gui.main_window import MainWindow
from storage.observation_export import save_observations


def profile(app,count,bounded):
    events=[PacketEvent(index,'RECV',127,b'\x7f\0abcd','SYNTHETIC','synthetic') for index in range(count)]
    results=[DisplayResult('test',f'message-{index}-'+'x'*500,'decoded') for index in range(count)]
    gc.collect()
    state=SimpleNamespace(events=events,display_results=results,table=QTableWidget(0,6),
        display_log=QPlainTextEdit(),DISPLAY_TEXT_LIMIT=MainWindow.DISPLAY_TEXT_LIMIT)
    if bounded:state.display_log.setMaximumBlockCount(5000)
    before=psutil.Process().memory_info().rss
    tracemalloc.start()
    started=perf_counter()
    for index,result in enumerate(results):
        if bounded and index%1000==0:state.table.setRowCount(0)
        MainWindow.insert_packet_row(state,index)
        if bounded:MainWindow.append_display_text(state,result.text)
        else:state.display_log.appendPlainText(result.text)
    app.processEvents()
    elapsed=(perf_counter()-started)*1000
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    rss_delta=psutil.Process().memory_info().rss-before
    row=dict(bounded=bounded,retained_events=len(events),retained_results=len(results),
        widget_rows=state.table.rowCount(),document_characters=state.display_log.document().characterCount()-1,
        document_blocks=state.display_log.blockCount(),render_ms=round(elapsed,3),
        python_peak_bytes=peak,rss_delta_bytes=rss_delta)
    assert len(events)==count and len(results)==count
    if bounded:assert row['widget_rows']<=1000 and row['document_characters']<=MainWindow.DISPLAY_TEXT_LIMIT
    state.table.close();state.display_log.close()
    state.table.deleteLater();state.display_log.deleteLater()
    from PySide6.QtCore import QCoreApplication,QEvent
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    app.processEvents()
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    rows=[profile(app,count,bounded) for count in (1000,10000) for bounded in (False,True)]
    save_observations(args.output,dict(kind='packet_history_widget_profile',source='synthetic',
        includes_capture_database_decoding=False,model_allocations_included=False,
        python_peak_includes_qt_allocations=False,rss_allocator_and_order_sensitive=True,scenarios=rows))
    for row in rows:print(row,flush=True)


if __name__=='__main__':main()
