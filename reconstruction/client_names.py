"""Client labels for GUI projection only; never modify observed identifiers."""
import hashlib
import json
from pathlib import Path
import re
from reconstruction.skill_catalog import read_bounded,unique_json_object
from reconstruction.instance_names import map_name as instance_base

DEFAULT_CLIENT_NAMES=Path(__file__).resolve().parents[1]/'config/client_names.json'
TABLES={'item_identified','maps','quests'}


def empty_client_names():
    return dict(tables={key:{} for key in TABLES},_sha256=None)


def load_client_names(path=DEFAULT_CLIENT_NAMES):
    raw=read_bounded(path,2*1024*1024)
    document=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_json_object)
    if (type(document) is not dict or type(document.get('version')) is not int or document['version']!=1
            or type(document.get('tables')) is not dict or set(document['tables'])!=TABLES):
        raise ValueError('Invalid client-name catalog')
    for namespace,rows in document['tables'].items():
        if type(rows) is not dict or len(rows)>65536:raise ValueError('Invalid name table')
        for key,value in rows.items():
            valid_key=(isinstance(key,str) and bool(re.fullmatch(r'[A-Za-z0-9_@-]+\.rsw',key)) if namespace=='maps'
                       else isinstance(key,str) and key.isascii() and key.isdecimal()
                       and str(int(key))==key and 0<int(key)<=0xffffffff)
            names=value if namespace=='quests' else [value]
            if (not valid_key or type(names) is not list or not 1<=len(names)<=16
                    or any(not isinstance(name,str) or not name.strip() or len(name)>256
                           or not all(c.isprintable() or c=='\u3000' for c in name) for name in names)
                    or len(set(names))!=len(names)):
                raise ValueError('Invalid client name entry')
    document['_sha256']=hashlib.sha256(raw).hexdigest()
    return document


def item_name(catalog,item_id):
    # Reference label only; identification is a separate observed item property.
    return catalog['tables']['item_identified'].get(str(item_id),'未登録')


def map_label(catalog,raw_map,navigation=None):
    if not isinstance(raw_map,str):return ''
    base=instance_base(raw_map)
    # Strip only a complete runtime instance prefix; change extensions for lookup.
    if base.endswith(('.gat','.rsw')):base=base[:-4]
    label=catalog['tables']['maps'].get(base+'.rsw','')
    if label or navigation is None:return label
    from reconstruction.navigation import navigation_map_names
    labels=navigation_map_names(navigation,raw_map)
    return ' / '.join(labels)+('（名称候補）' if len(labels)>1 else '')


def quest_label(catalog,quest_id):
    names=catalog['tables']['quests'].get(str(quest_id),[])
    return ' / '.join(names)+('（名称候補）' if len(names)>1 else '')


def quest_reference(catalog,quest_id):
    label=quest_label(catalog,quest_id)
    return f'ID={quest_id}'+(f' ({label})' if label else '')
