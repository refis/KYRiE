"""Display-only symbols in separate client ID namespaces."""
import hashlib
import json
from pathlib import Path
import re
from reconstruction.skill_catalog import read_bounded,unique_json_object

DEFAULT_REFERENCE_NAMES=Path(__file__).resolve().parents[1]/'config/reference_names.json'
REFERENCE_FIELDS=dict(reference_symbols='',reference_description='',reference_namespace='',
                      reference_known=False,reference_catalog_sha256='')
PREFIXES={'visual_effect':'EF_', 'status_icon':'EFST_'}
PACKETS={'visual_effect':{0x19b:10,0x1f3:10,0xb0d:10,0x284:14},
         'status_icon':{0x196:9,0x43f:25,0x983:29}}
DESCRIPTION_MISSING='説明未登録'
MAX_DESCRIPTION_CHARS=256


def _validate_descriptions(document,catalogs):
    """Optional Japanese labels; never alter symbol catalogs or SC conversion."""
    descriptions=document.get('descriptions',None)
    if descriptions is None:
        document['descriptions']={namespace:{} for namespace in PREFIXES}
        return
    if type(descriptions) is not dict or set(descriptions)!=set(PREFIXES):
        raise ValueError('Invalid reference-name descriptions')
    for namespace,rows in descriptions.items():
        if type(rows) is not dict or len(rows)>65536:
            raise ValueError('Invalid reference-name descriptions')
        known=catalogs[namespace]
        for key,text in rows.items():
            if (not isinstance(key,str) or not key.isascii() or not key.isdecimal()
                    or str(int(key))!=key or key not in known
                    or not isinstance(text,str) or not 1<=len(text)<=MAX_DESCRIPTION_CHARS
                    or '\0' in text or '\r' in text or '\n' in text):
                raise ValueError('Invalid reference-name description entry')
    source=document.get('description_sources',None)
    if source is None:
        return
    if type(source) is not list or len(source)>32:
        raise ValueError('Invalid reference-name description_sources')
    for row in source:
        if (type(row) is not dict
                or not isinstance(row.get('namespace'),str) or row['namespace'] not in PREFIXES
                or not isinstance(row.get('path'),str) or not row['path']
                or not isinstance(row.get('sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',row['sha256'])
                or not isinstance(row.get('field'),str) or not row['field']
                or (row.get('encoding') is not None and not isinstance(row['encoding'],str))):
            raise ValueError('Invalid reference-name description_sources')


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
    _validate_descriptions(document,catalogs)
    document['_sha256']=hashlib.sha256(raw).hexdigest()
    return document


def reference_labels(catalog,namespace,number):
    key=str(number)
    symbols=catalog['catalogs'][namespace].get(key,[])
    description=catalog.get('descriptions',{}).get(namespace,{}).get(key)
    return dict(reference_symbols=' / '.join(symbols) if symbols else '未登録',
                reference_description=description if description else DESCRIPTION_MISSING,
                reference_namespace=namespace,reference_known=bool(symbols),
                reference_catalog_sha256=catalog['_sha256'])
