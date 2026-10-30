"""Offscreen MOB detail-render timing, without capture, database writes or live-game checks."""
import argparse
import json
import os
from pathlib import Path
from statistics import median
import struct
import sys
from time import perf_counter

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QApplication
from events import PacketEvent
from reconstruction.world import WorldStore
from reconstruction.skills import SkillStore
from reconstruction.combat import CombatStore
from gui.skills import MobSkillPanel
from gui.combat import MobPerformancePanel
from storage.observation_export import save_observations
from storage.project import fingerprint
from parser.definitions import load_lengths
from tools.replay_capture import replay


def stores():
    world=WorldStore()
    return world,SkillStore(world),CombatStore(world)


def consume(models,event,index):
    world,skills,combat=models
    world.apply(event,packet_index=index)
    skills.apply(event,packet_index=index)
    combat.apply(event,packet_index=index)


def synthetic(count,casts=False):
    models=stores();index=0
    raw=bytearray(88);struct.pack_into('<HHBI',raw,0,0x9ff,len(raw),5,42)
    struct.pack_into('<H',raw,13,150);struct.pack_into('<H',raw,23,1005)
    raw[84:]=b'MOB\0'
    consume(models,PacketEvent(0,'RECV',0x9ff,bytes(raw),'SYNTHETIC','flow'),index)
    for number in range(count):
        timestamp=(number+1)/10;tick=(number+1)*1000
        attack=bytearray(34);struct.pack_into('<HIIIii',attack,0,0x8c8,42,99,tick,120,80)
        struct.pack_into('<i',attack,22,10);struct.pack_into('<hB',attack,27,1,0)
        skill=bytearray(33);struct.pack_into('<HHIIIiiiHhB',skill,0,0x1de,177,42,99,tick,120,80,10,3,1,8)
        if casts:
            cast=bytearray(24);struct.pack_into('<HIIHHH',cast,0,0x13e,42,99,10,20,177)
            struct.pack_into('<I',cast,20,10)
            index+=1;consume(models,PacketEvent(timestamp-.01,'RECV',0x13e,bytes(cast),'SYNTHETIC','flow'),index)
        for pid,data in ((0x8c8,attack),(0x1de,skill)):
            index+=1;consume(models,PacketEvent(timestamp,'RECV',pid,bytes(data),'SYNTHETIC','flow'),index)
        if number%100==0:
            index+=1
            percent=struct.pack('<HIB',0xa36,42,20-(number//100)%20)
            consume(models,PacketEvent(timestamp,'RECV',0xa36,percent,'SYNTHETIC','flow'),index)
    return models,dict(kind='synthetic',cast_heavy=casts,notifications_per_series=count,packet_count=index+1)


def from_log(path,definitions):
    path=Path(path).resolve();definition_path=Path(definitions).resolve()
    before=fingerprint(path,128*1024*1024)
    definitions_hash=fingerprint(definition_path,4*1024*1024)
    models=stores();count=0
    def packet(event):
        nonlocal count
        consume(models,event,count);count+=1
    result=replay(path,load_lengths(definition_path),on_packet=packet)
    if (fingerprint(path,128*1024*1024)!=before
            or fingerprint(definition_path,4*1024*1024)!=definitions_hash):raise ValueError('Input changed during profiling')
    return models,dict(kind='saved_log',source=str(path),sha256=before,definitions=str(definition_path),definitions_sha256=definitions_hash,packet_count=count,replay=result)


def measure(models,runs,app):
    world,skills,combat=models
    skill=MobSkillPanel(skills,lambda _:None,{},combat=combat)
    performance=MobPerformancePanel(combat,lambda _:None,{})
    performance.rebuild()
    result={}
    try:
        for name,panel in (('skills',skill),('performance',performance)):
            if not panel.rows:
                result[name]=dict(no_rows=True);continue
            row=max(range(len(panel.rows)),key=lambda i:len(panel.rows[i]['evidence']))
            blocker=QSignalBlocker(panel.table);panel.table.setCurrentCell(row,0);del blocker
            timings=[]
            for _ in range(runs):
                started=perf_counter();panel.show_selected();app.processEvents()
                timings.append(round((perf_counter()-started)*1000,3))
            refresh=[]
            for _ in range(runs):
                started=perf_counter();panel.refresh();app.processEvents()
                refresh.append(round((perf_counter()-started)*1000,3))
            result[name]=dict(unchanged_refresh_ms=refresh,cast_rows=panel.cast_review.table.rowCount() if name=='skills' else None,class_id=panel.rows[row]['class_id'],render_ms=timings,median_ms=median(timings),
                json_preview_bytes=len(panel.detail.toPlainText().encode('utf-8')),interval_rows=panel.interval_table.rowCount(),
                model_observations=len(panel.store.events))
        return result
    finally:
        skill.close();performance.close();skill.deleteLater();performance.deleteLater();app.processEvents()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events',type=int,nargs='+',default=[1000,5000])
    parser.add_argument('--casts',action='store_true')
    parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--log')
    parser.add_argument('--definitions')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not 1<=args.runs<=5 or len(args.events)>5 or any(not 1<=n<=25000 for n in args.events):
        parser.error('Use 1..5 runs, at most five sizes of 1..25000 notifications')
    if args.log and not args.definitions:parser.error('--log requires --definitions')
    app=QApplication.instance() or QApplication([])
    rows=[]
    for size in ([None] if args.log else args.events):
        models,source=from_log(args.log,args.definitions) if args.log else synthetic(size,args.casts)
        rows.append(dict(source=source,measurements=measure(models,args.runs,app)))
    report=dict(kind='mob_view_profile',python=sys.version,qt_mode=os.environ.get('QT_QPA_PLATFORM'),runs=args.runs,
                includes_capture_or_db=False,includes_export_timing=False,scenarios=rows)
    save_observations(args.output,report,[args.log,args.definitions])
    for row in rows:
        print(json.dumps(dict(source=row['source'].get('kind'),size=row['source']['packet_count'],measurements=row['measurements']),ensure_ascii=False))


if __name__=='__main__':main()
