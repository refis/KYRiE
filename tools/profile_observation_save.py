"""Measure extra allocations for synthetic observation-text export only."""
import argparse
import hashlib
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter
from storage.observation_export import save_observation_bytes,save_observations


def profile(count,mode,folder,app=None):
    records=[f'{index}:観測:'+('あ'*256) for index in range(count)]
    destination=Path(folder)/'observations.txt'
    if mode=='worker':
        from gui.observation_save import ObservationSaveWorker
        from PySide6.QtCore import QTimer
        from PySide6.QtTest import QTest
        pulses=[]
        timer=QTimer();timer.setInterval(1)
        timer.timeout.connect(lambda:pulses.append(perf_counter()))
        timer.start()
    def chunks():
        for index,text in enumerate(records):
            if index:yield '\n'
            yield text
    tracemalloc.start()
    started=perf_counter()
    callback_returned=None
    if mode=='buffered':save_observation_bytes(destination,'\n'.join(records).encode('utf-8'))
    elif mode=='stream':
        from storage.observation_export import save_observation_chunks
        save_observation_chunks(destination,chunks())
    else:
        worker=ObservationSaveWorker(destination,chunks(),[])
        worker.start()
        callback_returned=perf_counter()
        while worker.isRunning():
            app.processEvents();QTest.qWait(1)
        worker.wait()
        assert worker.result['status']=='saved'
        timer.stop()
    elapsed=(perf_counter()-started)*1000
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    digest=hashlib.sha256()
    with destination.open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):digest.update(chunk)
    row=dict(records=count,mode=mode,output_bytes=destination.stat().st_size,
        output_sha256=digest.hexdigest(),extra_python_peak_bytes=peak,elapsed_ms=round(elapsed,3))
    if mode=='worker':
        points=[started,*pulses,started+elapsed/1000]
        row.update(callback_ms=round((callback_returned-started)*1000,3),heartbeat_count=len(pulses),
            max_heartbeat_gap_ms=round(max(b-a for a,b in zip(points,points[1:]))*1000,3))
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['buffered','stream','worker'],required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    app=None
    if args.mode=='worker':
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='kyrie-save-profile-') as folder:
        rows=[profile(count,args.mode,folder,app) for count in (10000,50000)]
    save_observations(args.output,dict(kind='observation_save_profile',source='synthetic',
        input_history_allocations_included=False,includes_capture_or_widgets=False,
        includes_qt_event_loop=args.mode=='worker',scenarios=rows))
    for row in rows:print(row,flush=True)


if __name__=='__main__':main()
