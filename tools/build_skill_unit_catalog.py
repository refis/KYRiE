"""Build static unit labels from local references without executing their code."""
import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path
import re

from reconstruction.skill_catalog import read_bounded, digest, parse_table
from reconstruction.skills import DEFAULT_NAMES, validate_skill_names
from reconstruction.skill_units import load_unit_catalog

ROOT=Path(__file__).resolve().parents[1]


def maria_units(data):
    tree=ast.parse(data)
    nodes=[node.value for node in tree.body if isinstance(node,ast.Assign)
           and any(isinstance(target,ast.Name) and target.id=='UNITID' for target in node.targets)]
    if len(nodes)!=1 or not isinstance(nodes[0],ast.Dict):raise ValueError('Expected one UNITID table')
    result={}
    for key,value in zip(nodes[0].keys,nodes[0].values):
        if not isinstance(key,ast.Constant) or not isinstance(value,ast.Constant):raise ValueError('Nonliteral UNITID')
        number,symbol=key.value,value.value
        if type(number) is not int or number in result or not isinstance(symbol,str) or not re.fullmatch(r'UNT_[A-Z0-9_]+',symbol):
            raise ValueError('Invalid or duplicate UNITID')
        result[number]=symbol
    return result


def auriga_units(data):
    clean=re.sub(rb'/\*.*?\*/|//[^\r\n]*',b'',data,flags=re.S)
    tables=re.findall(rb'enum\s*\{([^{}]*\bUNT_SAFETYWALL\b[^{}]*)\}',clean,re.S)
    if len(tables)!=1:raise ValueError('Expected one Auriga unit enum')
    result={};value=-1
    for entry in tables[0].split(b','):
        if not entry.strip():continue
        match=re.fullmatch(rb'\s*(UNT_[A-Z0-9_]+)(?:\s*=\s*(0[xX][0-9a-fA-F]+|[0-9]+))?\s*',entry)
        if not match:raise ValueError('Unsupported C enum expression')
        value=int(match[2],0) if match[2] else value+1
        if value in result:raise ValueError('Duplicate C unit number')
        result[value]=match[1].decode('ascii')
    return result


def build_catalog(maria_path,auriga_root,skillid_path,names_path=DEFAULT_NAMES):
    paths=[Path(maria_path),Path(auriga_root)/'src/map/skill.h',Path(auriga_root)/'db/skill_unit_db.txt',Path(skillid_path),Path(names_path)]
    blobs=[read_bounded(path) for path in paths]
    maria,auriga=maria_units(blobs[0]),auriga_units(blobs[1])
    ids=parse_table(blobs[3],'SKID')
    names=validate_skill_names(json.loads(blobs[4].decode('utf-8')))
    units={};conflicts=[]
    for number in sorted(set(maria)|set(auriga)):
        if number in maria and number in auriga and maria[number]!=auriga[number]:
            conflicts.append(dict(id=number,maria=maria[number],auriga=auriga[number]));continue
        symbol=auriga.get(number,maria.get(number))
        basis='maria_auriga_agree' if number in maria and number in auriga else 'auriga_only' if number in auriga else 'maria_only'
        units[str(number)]=dict(symbol=symbol,basis=basis,skills=[])
    links=defaultdict(set);unresolved=[]
    for line_no,line in enumerate(blobs[2].splitlines(),1):
        line=line.split(b'//',1)[0].strip()
        if not line:continue
        fields=line.split(b',')
        if len(fields)!=9:
            unresolved.append(dict(line=line_no,reason='unsupported_db_layout'));continue
        skill=int(fields[0]);symbol=fields[8].split(b'#',1)[0].strip().decode('ascii')
        if ids.get(symbol)!=skill or skill not in names:
            unresolved.append(dict(line=line_no,skill_id=skill,symbol=symbol));continue
        for field in fields[1:3]:
            field=field.strip()
            if not field:continue
            number=int(field,0)
            if number and str(number) in units:links[number].add(skill)
            elif number:unresolved.append(dict(line=line_no,unit_id=number,reason='unresolved_unit_definition'))
    for number,skills in links.items():
        units[str(number)]['skills']=[dict(id=skill,name=names[skill]) for skill in sorted(skills)]
    sources=[dict(path=str(path.resolve()),sha256=digest(blob)) for path,blob in zip(paths,blobs)]
    return dict(version=1,namespace='skill_unit_type',sources=sources,units=units,
                definition_conflicts=conflicts,unresolved_skill_links=unresolved,
                used_skill_inferred=False)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--auriga-root',type=Path,required=True)
    cli.add_argument('--maria',type=Path,default=ROOT/'.reference/MARiA/const.py')
    cli.add_argument('--skillid',type=Path,default=ROOT/'.reference/data/luafiles514/lua files/skillinfoz/skillid.lua')
    cli.add_argument('--output',type=Path,default=ROOT/'config/skill_units.json')
    args=cli.parse_args()
    document=build_catalog(args.maria,args.auriga_root,args.skillid)
    # This is a developer catalog builder, separate from runtime profile loading.
    import os,tempfile
    temporary=None
    destination=args.output.resolve()
    protected={Path(row['path']).resolve() for row in document['sources']}
    if destination in protected or destination.is_relative_to(ROOT/'.reference'):
        cli.error('Cannot overwrite reference or input files')
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.json',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write((json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        load_unit_catalog(temporary)
        for row in document['sources']:
            if digest(read_bounded(row['path']))!=row['sha256']:raise ValueError('Catalog source changed')
        os.replace(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    print(f"Units {len(document['units'])}; conflicts {len(document['definition_conflicts'])}; unresolved links {len(document['unresolved_skill_links'])}")


if __name__=='__main__':main()
