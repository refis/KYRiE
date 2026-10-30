"""Observed appearance and projection helpers; raw classes are retained."""
import json
from pathlib import Path
from reconstruction.instance_names import npc_name

JOB_IDS_PATH = Path(__file__).resolve().parents[1] / 'config' / 'player_classes.json'
JOB_IDS = frozenset(json.loads(JOB_IDS_PATH.read_text(encoding='utf-8'))['ids'])
VISUAL_FIELDS = ('sex','cloth_color','hair_style','hair_color','head_top','head_mid','head_bottom','robe','style')
OBSERVED_FIELDS = ('class_id','name','x','y','direction','destination_x','destination_y','speed','options','appearance_data')


def player_class(value):
    return type(value) is int and value in JOB_IDS


def declaration_class(npc):
    initial = npc.get('initial_display') or {}
    value = initial.get('class_id', npc.get('class_id'))
    return 844 if player_class(value) else value


def display_values(npc, display, require_full=False):
    if type(display.get('class_id')) is not int or not 0 <= display['class_id'] <= 65535:
        return None
    name = json.dumps(npc_name(npc.get('name',''),npc.get('map_name')),ensure_ascii=False)
    values = dict(target=name,class_id=display['class_id'])
    visual = display.get('appearance_data') or {}
    if player_class(display['class_id']) and (visual or require_full):
        if any(type(visual.get(k)) is not int or not 0 <= visual[k] <= 65535 for k in VISUAL_FIELDS) or visual['sex'] not in (0,1):
            return None
        values.update(visual)
    return values


def render_display(npc, display, style, *, outside=False, require_full=False):
    values = display_values(npc,display,require_full)
    if not values or not npc.get('name'):
        return style['npc_display_unknown']
    if '@' in (npc.get('map_name') or ''):
        values['target'] = style['instance_npc_reference'].format(name=values['target'])
    code = style['npc_display_full' if 'sex' in values else 'npc_display_class'].format_map(values)
    return style['npc_display_outside'].format(code=code) if outside else code
