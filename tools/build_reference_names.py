"""Statically extract client EF/EFST constants; never execute Lua guard functions."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import tempfile
from reconstruction.skill_catalog import tokenize,TableParser,read_bounded,digest
from reconstruction.reference_names import PREFIXES,load_reference_names,DEFAULT_REFERENCE_NAMES

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.reference/data/luafiles514/lua files'


def constants(raw,name,prefix):
    ignored_guard=False
    if name=='EFST_IDs':
        raw,count=re.subn(rb',\s*__newindex\s*=\s*function\(\)\s*error\("unknown state"\)\s*end\s*}\s*setmetatable\(EFST_IDs,\s*EFST_IDs\)\s*$',b'}',raw)
        ignored_guard=bool(count)
    parser=TableParser(tokenize(raw,'cp932'))
    if parser.take('name')!=name:raise ValueError('Unexpected constant table')
    parser.take('=');parser.take('{')
    result={};duplicates=[]
    while parser.tokens[parser.index][0]!='}':
        symbol=parser.take('name');parser.take('=');number=parser.take('number')
        if not re.fullmatch(prefix+r'[A-Z0-9_]+',symbol) or type(number) is not int or not 0<=number<=0xffffffff:
            raise ValueError('Invalid constant')
        if symbol in result:
            if result[symbol]!=number:raise ValueError('Conflicting constant: '+symbol)
            duplicates.append(dict(symbol=symbol,id=number))
        result[symbol]=number
        if parser.tokens[parser.index][0] not in (',',';'):break
        parser.index+=1
    parser.take('}');parser.take('eof')
    grouped=defaultdict(list)
    for symbol,number in result.items():grouped[number].append(symbol)
    return {str(key):sorted(value) for key,value in sorted(grouped.items())},duplicates,ignored_guard


def build_catalog(effect_path,status_path):
    catalogs={};sources=[];duplicates=[];guards=[]
    for namespace,path,table in (('visual_effect',effect_path,'EFID'),('status_icon',status_path,'EFST_IDs')):
        raw=read_bounded(path)
        rows,repeated,ignored=constants(raw,table,PREFIXES[namespace])
        catalogs[namespace]=rows
        sources.append(dict(namespace=namespace,path=str(Path(path).resolve()),sha256=digest(raw)))
        duplicates.extend(dict(namespace=namespace,**row) for row in repeated)
        if ignored:guards.append(table)
    return dict(version=1,catalogs=catalogs,sources=sources,identical_duplicates=duplicates,
                ignored_known_guard_tables=guards,script_id_conversion=False)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--effects',type=Path,default=BASE/'skilleffectinfo/effectid.lua')
    cli.add_argument('--status',type=Path,default=BASE/'stateicon/efstids.lua')
    cli.add_argument('--output',type=Path,default=DEFAULT_REFERENCE_NAMES)
    args=cli.parse_args()
    document=build_catalog(args.effects,args.status);destination=args.output.resolve()
    if destination.is_relative_to(ROOT/'.reference') or destination in {Path(row['path']) for row in document['sources']}:
        cli.error('Reference and source files are read-only')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.json',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write((json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        load_reference_names(temporary)
        for row in document['sources']:
            if digest(read_bounded(row['path']))!=row['sha256']:raise ValueError('Reference source changed')
        os.replace(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    print('Catalog IDs: '+', '.join(f'{key}={len(value)}' for key,value in document['catalogs'].items()))


if __name__=='__main__':main()
