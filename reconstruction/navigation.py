"""Static navigation references. IDs and numeric columns are never actor observations."""
import json
import re
from pathlib import Path
from reconstruction.skill_catalog import read_bounded,digest,unique_json_object
from reconstruction.instance_names import map_name as instance_base

DEFAULT_NAVIGATION=Path(__file__).resolve().parents[1]/'config/navigation.json'
MAX_NAVIGATION=4*1024*1024
SCHEMAS={'maps':(str,str,int,int,int),'npcs':(str,int,int,int,str,str,int,int),
         'mobs':(str,int,int,int,str,str,int,int),'links':(str,int,int,int,str,str,int,int,str,int,int),
         'scrolls':(str,int,int,str,int,int),'picknpcs':(str,int,int,int,int,int,int,int,int,int,int,int)}


def empty_navigation():
    return dict(tables={key:[] for key in SCHEMAS},_sha256=None)


def validate_navigation(document):
    if (type(document) is not dict or type(document.get('version')) is not int or document['version']!=1
            or type(document.get('tables')) is not dict or set(document['tables'])!=set(SCHEMAS)):
        raise ValueError('Invalid navigation catalog')
    for key,rows in document['tables'].items():
        if type(rows) is not list or len(rows)>20000:raise ValueError('Navigation table limit')
        for row in rows:
            if type(row) is not list or len(row)!=len(SCHEMAS[key]):raise ValueError('Invalid navigation row')
            for value,kind in zip(row,SCHEMAS[key]):
                if type(value) is not kind:raise ValueError('Invalid navigation column type')
                if kind is int and not 0<=value<=0xffffffff:raise ValueError('Invalid navigation number')
                if kind is str and (len(value)>256 or not all(c.isprintable() or c=='\u3000' for c in value)):
                    raise ValueError('Invalid navigation text')
            if not re.fullmatch(r'[A-Za-z0-9_@-]+',row[0]):raise ValueError('Invalid navigation map')
    return document


def load_navigation(path=DEFAULT_NAVIGATION):
    raw=read_bounded(path,MAX_NAVIGATION)
    document=validate_navigation(json.loads(raw.decode('utf-8'),object_pairs_hook=unique_json_object))
    document['_sha256']=digest(raw)
    return document


def lookup_map(raw_map):
    if not isinstance(raw_map,str):return ''
    key=instance_base(raw_map)
    return key[:-4] if key.endswith(('.gat','.rsw')) else key


def navigation_map_names(catalog,raw_map):
    key=lookup_map(raw_map)
    return list(dict.fromkeys(row[1] for row in catalog['tables']['maps'] if row[0]==key and row[1].strip()))
