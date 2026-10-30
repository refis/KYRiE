"""Build bounded item/map/quest name labels from provided text, never execute code."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from reconstruction.skill_catalog import read_bounded,digest
from reconstruction.client_names import DEFAULT_CLIENT_NAMES,load_client_names

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DATA=ROOT/'.reference/data'


def pairs(raw,numeric=True):
    result={};empty=[];seen=set()
    for number,line in enumerate(raw.decode('cp932').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('//'):continue
        match=re.fullmatch(r'([^#]+)#([^#]*)#(?:\s*//.*)?',line)
        if not match:raise ValueError(f'Invalid name record at line {number}')
        key,name=match.groups()
        if numeric:
            if not key.isascii() or not key.isdecimal() or str(int(key))!=key:raise ValueError('Invalid numeric name ID')
        if key in seen:raise ValueError('Duplicate name record: '+key)
        seen.add(key)
        if not name.strip():
            empty.append(dict(key=key,line=number));continue
        result[key]=name
    return result,empty


def quests(raw):
    text='\n'.join(line for line in raw.decode('cp932').splitlines() if not line.lstrip().startswith('//'))
    fields=text.split('#')
    if fields[-1].strip() or (len(fields)-1)%6:raise ValueError('Invalid six-field quest format')
    result={};duplicates=[]
    for offset in range(0,len(fields)-1,6):
        key=fields[offset].strip();name=fields[offset+1]
        if not key.isascii() or not key.isdecimal() or str(int(key))!=key:raise ValueError('Invalid quest ID')
        if key in result:duplicates.append(dict(id=int(key),name=name))
        if name not in result.setdefault(key,[]):result[key].append(name)
    return result,duplicates


def build_catalog(root):
    sources=[];tables={};empty_names=[]
    for namespace,filename in (('item_identified','idnum2itemdisplaynametable.txt'),
                               ('maps','mapnametable.txt'),
                               ('quests','questid2display.txt')):
        path=Path(root)/filename;raw=read_bounded(path)
        sources.append(dict(path=str(path.resolve()),sha256=digest(raw)))
        if namespace=='quests':tables[namespace],duplicates=quests(raw)
        else:
            tables[namespace],empty=pairs(raw,namespace!='maps')
            empty_names.extend(dict(namespace=namespace,**row) for row in empty)
    return dict(version=1,tables=tables,sources=sources,quest_duplicates=duplicates,empty_names=empty_names,
                observation_values_modified=False)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data',type=Path,default=DEFAULT_DATA)
    cli.add_argument('--output',type=Path,default=DEFAULT_CLIENT_NAMES)
    args=cli.parse_args();document=build_catalog(args.data);destination=args.output.resolve()
    if destination.is_relative_to(ROOT/'.reference') or destination in {Path(r['path']) for r in document['sources']}:
        cli.error('Reference and input files are read-only')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.json',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write((json.dumps(document,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8'))
        load_client_names(temporary)
        for source in document['sources']:
            if digest(read_bounded(source['path']))!=source['sha256']:raise ValueError('Source changed')
        os.replace(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    print(', '.join(f'{key}={len(value)}' for key,value in document['tables'].items()))


if __name__=='__main__':main()
