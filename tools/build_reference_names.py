"""Statically extract client EF/EFST constants; never execute Lua guard functions."""
import argparse
import ast
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import tempfile
from reconstruction.skill_catalog import tokenize,TableParser,read_bounded,digest
from reconstruction.reference_names import (
    PREFIXES, load_reference_names, DEFAULT_REFERENCE_NAMES, MAX_DESCRIPTION_CHARS)

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.reference/data/luafiles514/lua files'
STATUS_INFO_TABLES=('StateIconList','StateIconInfoList')


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


def maria_statuses(raw):
    tree=ast.parse(raw.decode('utf-8-sig'))
    assignments=[node.value for node in tree.body if isinstance(node,ast.Assign)
                 and any(isinstance(target,ast.Name) and target.id=='EFST' for target in node.targets)]
    if len(assignments)!=1 or not isinstance(assignments[0],ast.Dict):
        raise ValueError('Expected one literal MARiA EFST dictionary')
    result={};symbols=set()
    for key,value in zip(assignments[0].keys,assignments[0].values):
        if not isinstance(key,ast.Constant) or not isinstance(value,ast.Constant):
            raise ValueError('Computed MARiA EFST entry')
        number,symbol=key.value,value.value
        if (type(number) is not int or not 0<=number<=0xffffffff or not isinstance(symbol,str)
                or not re.fullmatch(r'EFST_[A-Z0-9_]+',symbol) or number in result or symbol in symbols):
            raise ValueError('Invalid or duplicate MARiA EFST entry')
        result[number]=symbol;symbols.add(symbol)
    return result


def supplement_statuses(rows,additional):
    result={key:list(value) for key,value in rows.items()};added=[];agreed=0
    reverse={symbol:int(key) for key,values in rows.items() for symbol in values}
    for number,symbol in sorted(additional.items()):
        key=str(number)
        if (key in result and symbol not in result[key]) or (symbol in reverse and reverse[symbol]!=number):
            raise ValueError('Conflicting Lua/MARiA status reference')
        if key in result:agreed+=1
        else:
            result[key]=[symbol];added.append(dict(id=number,symbol=symbol,basis='maria_only'))
    return result,added,agreed


def status_descriptions(raw,symbol_to_id,encoding='cp932'):
    """Pull descriptive= strings keyed by EFST_* from StateIconList-style tables."""
    parser=TableParser(tokenize(raw,encoding))
    found=None
    while parser.tokens[parser.index][0]!='eof':
        kind,value=parser.tokens[parser.index]
        if (kind=='name' and value in STATUS_INFO_TABLES
                and parser.tokens[parser.index+1][0]=='='):
            parser.index+=1;parser.take('=')
            found=parser.value()
            break
        parser.index+=1
    if found is None:
        raise ValueError('State icon description table not found')
    if type(found) is not dict:
        raise ValueError('Invalid state icon description table')
    result={};conflicts=[]
    for key,row in found.items():
        if isinstance(key,tuple) and key[0]=='ref' and key[1] in ('EFST_IDs','EFST'):
            symbol=key[2]
        elif isinstance(key,str) and key.startswith('EFST_'):
            symbol=key
        else:
            continue
        if type(row) is not dict or not isinstance(row.get('descriptive'),str):
            continue
        text=row['descriptive'].strip()
        if not text or len(text)>MAX_DESCRIPTION_CHARS or any(ch in text for ch in '\0\r\n'):
            raise ValueError('Invalid descriptive text for '+symbol)
        number=symbol_to_id.get(symbol)
        if number is None:
            continue
        key=str(number)
        if key in result and result[key]!=text:
            conflicts.append(symbol)
            continue
        result[key]=text
    if conflicts:
        raise ValueError('Conflicting descriptive text: '+', '.join(conflicts[:8]))
    return result


def build_catalog(effect_path,status_path,maria_path=None,status_info_path=None,status_info_encoding='cp932'):
    catalogs={};sources=[];duplicates=[];guards=[]
    for namespace,path,table in (('visual_effect',effect_path,'EFID'),('status_icon',status_path,'EFST_IDs')):
        raw=read_bounded(path)
        rows,repeated,ignored=constants(raw,table,PREFIXES[namespace])
        catalogs[namespace]=rows
        sources.append(dict(namespace=namespace,path=str(Path(path).resolve()),sha256=digest(raw)))
        duplicates.extend(dict(namespace=namespace,**row) for row in repeated)
        if ignored:guards.append(table)
    added=[];agreed=0
    if maria_path is not None:
        raw=read_bounded(maria_path)
        catalogs['status_icon'],added,agreed=supplement_statuses(catalogs['status_icon'],maria_statuses(raw))
        sources.append(dict(namespace='status_icon',path=str(Path(maria_path).resolve()),sha256=digest(raw),basis='maria_fallback'))
    descriptions={namespace:{} for namespace in PREFIXES}
    description_sources=[]
    if status_info_path is not None:
        raw=read_bounded(status_info_path)
        symbol_to_id={symbol:int(key) for key,values in catalogs['status_icon'].items() for symbol in values}
        descriptions['status_icon']=status_descriptions(raw,symbol_to_id,status_info_encoding)
        description_sources.append(dict(
            namespace='status_icon',path=str(Path(status_info_path).resolve()),
            sha256=digest(raw),field='descriptive',encoding=status_info_encoding))
    return dict(version=1,catalogs=catalogs,sources=sources,identical_duplicates=duplicates,
                supplemental_statuses=added,lua_maria_agreements=agreed,
                ignored_known_guard_tables=guards,script_id_conversion=False,
                descriptions=descriptions,description_sources=description_sources)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--effects',type=Path,default=BASE/'skilleffectinfo/effectid.lua')
    cli.add_argument('--status',type=Path,default=BASE/'stateicon/efstids.lua')
    cli.add_argument('--status-info',type=Path,default=None,
                     help='Optional stateiconinfo.lua for Japanese descriptive text')
    cli.add_argument('--status-info-encoding',choices=('cp932','utf-8'),default='cp932')
    cli.add_argument('--maria',type=Path,default=ROOT/'.reference/MARiA/const.py')
    cli.add_argument('--output',type=Path,default=DEFAULT_REFERENCE_NAMES)
    args=cli.parse_args()
    document=build_catalog(args.effects,args.status,args.maria,args.status_info,args.status_info_encoding)
    destination=args.output.resolve()
    protected={Path(row['path']) for row in document['sources']}
    protected.update(Path(row['path']) for row in document['description_sources'])
    if destination.is_relative_to(ROOT/'.reference') or destination in protected:
        cli.error('Reference and source files are read-only')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.json',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write((json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        load_reference_names(temporary)
        for row in document['sources']+document['description_sources']:
            if digest(read_bounded(row['path']))!=row['sha256']:raise ValueError('Reference source changed')
        os.replace(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    print('Catalog IDs: '+', '.join(f'{key}={len(value)}' for key,value in document['catalogs'].items()))
    print('Descriptions: '+', '.join(f'{key}={len(value)}' for key,value in document['descriptions'].items()))


if __name__=='__main__':main()
