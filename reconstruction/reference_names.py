"""Display-only symbols in separate client ID namespaces."""
import hashlib
import json
from pathlib import Path
import re
from reconstruction.skill_catalog import read_bounded,unique_json_object

DEFAULT_REFERENCE_NAMES=Path(__file__).resolve().parents[1]/'config/reference_names.json'
REFERENCE_FIELDS=dict(reference_symbols='',reference_namespace='',reference_known=False,reference_catalog_sha256='')
PREFIXES={'visual_effect':'EF_', 'status_icon':'EFST_'}
PACKETS={'visual_effect':{0x19b:10,0x1f3:10,0xb0d:10,0x284:14},
         'status_icon':{0x196:9,0x43f:25,0x983:29}}


def load_reference_names(path=DEFAULT_REFERENCE_NAMES):
    raw=read_bounded(path,1024*1024)
    document=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_json_object)
    if type(document) is not dict or type(document.get('version')) is not int or document['version']!=1:
        raise ValueError('Invalid reference-name catalog version')
    catalogs=document.get('catalogs')
    if type(catalogs) is not dict or set(catalogs)!=set(PREFIXES):
        raise ValueError('Invalid reference-name namespaces')
    for namespace,rows in catalogs.items():
        if type(rows) is not dict or len(rows)>65536:raise ValueError('Invalid reference-name entries')
        for key,symbols in rows.items():
            if (not isinstance(key,str) or not key.isascii() or not key.isdecimal()
                    or str(int(key))!=key or not 0<=int(key)<=0xffffffff
                    or type(symbols) is not list or not 1<=len(symbols)<=32
                    or any(not isinstance(s,str) or not re.fullmatch(PREFIXES[namespace]+r'[A-Z0-9_]+',s) for s in symbols)
                    or len(set(symbols))!=len(symbols)):
                raise ValueError('Invalid reference-name entry')
    document['_sha256']=hashlib.sha256(raw).hexdigest()
    return document


def reference_labels(catalog,namespace,number):
    symbols=catalog['catalogs'][namespace].get(str(number),[])
    return dict(reference_symbols=' / '.join(symbols) if symbols else '未登録',
                reference_namespace=namespace,reference_known=bool(symbols),
                reference_catalog_sha256=catalog['_sha256'])
