"""Build bounded navigation references from literal Lua tables without execution."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from reconstruction.skill_catalog import read_bounded,digest,parse_table
from reconstruction.navigation import DEFAULT_NAVIGATION,load_navigation,validate_navigation
ROOT=Path(__file__).resolve().parents[1]
FILES={'maps':('map','Navi_Map'),'npcs':('npc','Navi_Npc'),'mobs':('mob','Navi_Mob'),
       'links':('link','Navi_Link'),'scrolls':('scroll','Navi_Scroll'),'picknpcs':('picknpc','navi_picknpc')}


def build_catalog(root):
    tables={};sources=[]
    for key,(filename,symbol) in FILES.items():
        path=Path(root)/('navi_'+filename+'_jp.lua');raw=read_bounded(path)
        parsed=parse_table(raw,symbol)
        if set(parsed)!=set(range(1,len(parsed)+1)):raise ValueError('Non-sequential navigation table')
        rows=[]
        for i in range(1,len(parsed)+1):
            row=parsed[i]
            if type(row) is not dict or set(row)!=set(range(1,len(row)+1)):raise ValueError('Non-sequential row')
            rows.append([row[j] for j in range(1,len(row)+1)])
        tables[key]=rows
        sources.append(dict(path=str(path.resolve()),sha256=digest(raw),symbol=symbol))
    return validate_navigation(dict(version=1,tables=tables,sources=sources,
        observation_values_modified=False,numeric_columns_interpreted=False))


def write_catalog(document,destination):
    destination=Path(destination).resolve()
    if destination.is_relative_to(ROOT/'.reference') or destination in {Path(r['path']) for r in document['sources']}:
        raise ValueError('Reference and input files are read-only')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.json',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write((json.dumps(document,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8'))
        load_navigation(temporary)
        for source in document['sources']:
            if digest(read_bounded(source['path']))!=source['sha256']:raise ValueError('Source changed')
        os.replace(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data',type=Path,default=ROOT/'.reference/data/luafiles514/lua files/navigation')
    cli.add_argument('--output',type=Path,default=DEFAULT_NAVIGATION)
    args=cli.parse_args();document=build_catalog(args.data);write_catalog(document,args.output)
    print(', '.join(f'{key}={len(value)}' for key,value in document['tables'].items()))


if __name__=='__main__':main()
