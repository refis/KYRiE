"""Versioned unit-type labels; not skill-use inference or runtime actor identity."""
import json
import hashlib
from pathlib import Path
import re
from reconstruction.skill_catalog import read_bounded, unique_json_object

DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / 'config/skill_units.json'
UNIT_FIELDS = dict(unit_symbol='', unit_name='', unit_skill_ids='', unit_known=False,
                   unit_mapping_basis='',unit_catalog_sha256='')


def load_unit_catalog(path=DEFAULT_CATALOG):
    raw=read_bounded(path,1024*1024)
    document = json.loads(raw.decode('utf-8'),object_pairs_hook=unique_json_object)
    if type(document) is not dict or type(document.get('version')) is not int or document['version']!=1:
        raise ValueError('Invalid unit catalog version')
    if document.get('namespace')!='skill_unit_type' or document.get('used_skill_inferred') is not False:
        raise ValueError('Invalid unit catalog namespace or inference flag')
    units=document.get('units')
    if type(units) is not dict or len(units)>65536:
        raise ValueError('Invalid unit catalog')
    for key,row in units.items():
        if (not isinstance(key,str) or not key.isascii() or not key.isdecimal()
                or str(int(key))!=key or not 0<int(key)<=0xffffffff or type(row) is not dict
                or not isinstance(row.get('symbol'),str) or not re.fullmatch(r'UNT_[A-Z0-9_]+',row['symbol'])
                or row.get('basis') not in ('maria_auriga_agree','maria_only','auriga_only')
                or type(row.get('skills')) is not list or len(row['skills'])>512):
            raise ValueError('Invalid unit entry')
        seen=set()
        for skill in row['skills']:
            if (type(skill) is not dict or type(skill.get('id')) is not int or not 0<skill['id']<=65535
                    or skill['id'] in seen or not isinstance(skill.get('name'),str)
                    or not 0<len(skill['name'])<=256 or not all(c.isprintable() for c in skill['name'])):
                raise ValueError('Invalid unit skill link')
            seen.add(skill['id'])
    document['_sha256']=hashlib.sha256(raw).hexdigest()
    return document


def unit_labels(catalog, unit_id):
    row=catalog['units'].get(str(unit_id))
    if row is None:
        return dict(UNIT_FIELDS,unit_symbol='未登録',unit_name='対応未確認',
                    unit_catalog_sha256=catalog.get('_sha256',''))
    skills=row['skills']
    name=skills[0]['name'] if len(skills)==1 else (' / '.join(s['name'] for s in skills[:3])+f'（{len(skills)}候補）' if skills else 'スキル対応未確認')
    return dict(unit_symbol=row['symbol'],unit_name=name,
                unit_skill_ids=','.join(str(s['id']) for s in skills),unit_known=True,
                unit_mapping_basis=row['basis'],unit_catalog_sha256=catalog.get('_sha256',''))
