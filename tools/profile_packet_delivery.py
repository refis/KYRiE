"""Measure a synthetic producer burst while the Qt consumer is paused."""
import argparse
import gc
import os
import struct
import tracemalloc
from threading import Thread
from time import perf_counter
import psutil
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication
from events import PacketEvent
from gui.packet_delivery import Bridge
from storage.observation_export import save_observations


class Consumer(QObject):
    def __init__(self,bridge):
        super().__init__()
        self.bridge=bridge
        self.count=0
        self.ordered=True
        self.last=-1
    @Slot(object)
    def receive(self,delivery):
        self.bridge.accept(delivery)
        self.ordered &= delivery.event.timestamp==self.last+1
        self.last=delivery.event.timestamp
        self.count+=1


def profile(app,count,size,bounded):
    gc.collect()
    bridge=Bridge(max_pending=4096 if bounded else count+1,
        max_pending_bytes=16*1024*1024 if bounded else (count+1)*size)
    consumer=Consumer(bridge)
    bridge.packet.connect(consumer.receive)
    process=psutil.Process()
    before=process.memory_info().rss
    tracemalloc.start()
    started=perf_counter()
    def publish():
        for index in range(count):
            raw=struct.pack('<HI',127,index)+bytes(size-6)
            bridge.publish(1,PacketEvent(index,'RECV',127,raw,'SYNTHETIC','synthetic'))
    worker=Thread(target=publish);worker.start();worker.join()
    elapsed=(perf_counter()-started)*1000
    waiting=bridge.snapshot()
    _,peak=tracemalloc.get_traced_memory()
    rss_delta=process.memory_info().rss-before
    tracemalloc.stop()
    started=perf_counter()
    app.processEvents()
    drain_ms=(perf_counter()-started)*1000
    final=bridge.snapshot()
    assert final['awaiting_gui']==0 and final['pending_bytes']==0
    assert consumer.ordered and consumer.count==waiting['awaiting_gui']
    return dict(bounded=bounded,generated=count,raw_size=size,paused_consumer=waiting,
        python_peak_bytes=peak,rss_delta_bytes=rss_delta,publish_ms=round(elapsed,3),
        drain_ms=round(drain_ms,3),delivered=consumer.count,ordered=consumer.ordered)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    rows=[profile(app,10000,size,bounded) for size in (64,4096) for bounded in (False,True)]
    save_observations(args.output,dict(kind='packet_delivery_burst_profile',source='synthetic',
        includes_database_or_decoding=False,python_peak_includes_qt_allocations=False,
        rss_allocator_and_order_sensitive=True,scenarios=rows))
    for row in rows:print(row,flush=True)


if __name__=='__main__':main()
