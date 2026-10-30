"""Separate report construction and JSON/text serialization using synthetic data."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
from time import perf_counter
import tracemalloc
from reconstruction.world import Entity
from reconstruction.npc_bundle import build_npc_bundle
from storage.observation_export import save_observations,save_observation_text,save_observation_bytes
from tools.profile_mob_views import synthetic


def measured(action):
    tracemalloc.start();started=perf_counter()
    value=action()
    elapsed=(perf_counter()-started)*1000
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return value,dict(elapsed_ms=round(elapsed,3),extra_python_peak_bytes=peak)


def profile(folder,mode,deferred=False,npc_deferred=False,only_npc=False):
    rows=[]
    for count in (100,1000):
        entities=[asdict(Entity(1,'192.0.2.1:5121',1,1000+i,1,'NPC',6,'test.gat',0,0,
            name=f'案内{i}',class_id=139,x=i%200,y=i%200,direction=0)) for i in range(count)]
        if npc_deferred:
            from reconstruction.report_snapshot import freeze_npc_report
            prepared,freeze=measured(lambda:freeze_npc_report(entities,[],{1:'synthetic'},merge=True))
            report,build=measured(prepared.build)
        else:report,build=measured(lambda:build_npc_bundle(entities,[],{1:'synthetic'},merge=True))
        row=export(folder,'npc-'+str(count),report,build,mode)
        if npc_deferred:row['gui_freeze']=freeze
        rows.append(row)
    if only_npc:return rows
    for count in (1000,5000):
        _,skills,combat=synthetic(count)[0]
        for name,store in (('skills',skills),('performance',combat)):
            if deferred:
                from reconstruction.report_snapshot import freeze_mob_report
                prepared,freeze=measured(lambda:freeze_mob_report(store,{0:'synthetic'}))
                report,build=measured(prepared.build)
            else:
                report,build=measured(lambda:dict(deepcopy(store.snapshot()),source_sessions={'0':'synthetic'}))
            row=export(folder,name+'-'+str(count),report,build,mode)
            if deferred:row['gui_freeze']=freeze
            rows.append(row)
    return rows


def export(folder,name,report,build,mode):
    destination=Path(folder)/(name+'.json')
    def write_json():
        if mode=='buffered':
            save_observation_bytes(destination,(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
        else:save_observations(destination,report)
    _,serialization=measured(write_json)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    row=dict(scenario=name,build=build,json=serialization,json_bytes=destination.stat().st_size,json_sha256=digest)
    if 'auriga' in report:
        text=Path(folder)/(name+'.txt')
        def write_text():
            if mode=='buffered':save_observation_bytes(text,report['auriga'].encode('utf-8'))
            else:save_observation_text(text,report['auriga'])
        _,timing=measured(write_text)
        row.update(text=timing,text_bytes=text.stat().st_size,text_sha256=hashlib.sha256(text.read_bytes()).hexdigest())
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--mode',choices=['buffered','stream'],default='stream')
    parser.add_argument('--deferred',action='store_true')
    parser.add_argument('--npc-deferred',action='store_true')
    parser.add_argument('--only-npc',action='store_true')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='kyrie-report-profile-') as folder:rows=profile(folder,args.mode,args.deferred,args.npc_deferred,args.only_npc)
    save_observations(args.output,dict(kind='structured_export_profile',source='synthetic',
        includes_capture_database_or_gui=False,npc_conversations_included=False,mode=args.mode,deferred=args.deferred,npc_deferred=args.npc_deferred,scenarios=rows))
    for row in rows:print(row,flush=True)


if __name__=='__main__':main()
