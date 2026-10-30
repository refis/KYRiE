"""Auriga projection of observed group/title values, independent of acquisition."""
from reconstruction.render_inputs import read_render_json,render_profile_size
import json
from pathlib import Path
from string import Formatter
from reconstruction.decoder import Reader, ObservationError
from reconstruction.actor_appearance import player_class, render_display, VISUAL_FIELDS

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'entity_metadata.json'
FIELDS = {'npc_context': {'actor_id', 'actor_name'}, 'mob_context': {'actor_id', 'actor_name'},
          'oninit': set(), 'npc_group': {'group_id'}, 'npc_title': {'title'},
          'mob_group': {'group_id', 'actor_id'}, 'mob_title': {'title', 'actor_id'},
          'npc_display_class': {'target','class_id'}, 'npc_display_full': {'target','class_id',*VISUAL_FIELDS},
          'npc_display_unknown': set(), 'npc_display_outside': {'code'}, 'instance_npc_reference': {'name'},
          'waitingroom': {'title', 'limit'}, 'end': set(), 'indent': set(), 'conflict': set(), 'block_open': set(), 'block_close': set()}


def _entity_profile(path=None):
    from reconstruction.emulator_profiles import profile
    return Path(path) if path is not None else profile('entity_metadata.json')


def metadata_values(npc):
    evidence, issues = npc.get('metadata_evidence', {}), npc.get('field_issues', {})
    values = {}
    group = npc.get('group_id')
    if 'group_id' in evidence and 'group_id' not in issues and type(group) is int and 0 <= group <= 2147483647:
        values['group_id'] = group
    if 'title' in evidence and 'title' not in issues and isinstance(npc.get('title'), str):
        values['title'] = npc['title']
    return values


def templates(path=None):
    path = _entity_profile(path)
    if render_profile_size(path) > 65536:
        raise ValueError('個体メタデータ書式は64KiB以内にしてください。')
    result = read_render_json(path)
    if isinstance(result,dict):
        defaults=read_render_json(DEFAULT_PROFILE)
        for key in ('waitingroom','npc_display_class','npc_display_full','npc_display_unknown','npc_display_outside','instance_npc_reference'):
            result.setdefault(key,defaults[key])
    if not isinstance(result, dict) or set(result) != set(FIELDS):
        raise ValueError('個体メタデータ書式の項目が不正です。')
    for key, value in result.items():
        if not isinstance(value, str) or len(value) > 16384:
            raise ValueError('個体メタデータ書式が不正です。')
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None and (name not in FIELDS[key] or spec or conversion):
                raise ValueError('個体メタデータ書式の引数が不正です。')
    if result['oninit'] != 'OnInit:' or result['end'].strip() != 'end;':
        raise ValueError('初期化ラベル・終端が不正です。')
    if not 1 <= len(result['indent']) <= 16 or any(c not in ' \t' for c in result['indent']):
        raise ValueError('個体メタデータのインデントが不正です。')
    return result


def commands(values, kind, actor_id, style):
    values = display_values(values)
    args = dict(values, actor_id=actor_id)
    if 'title' in args:
        args['title'] = json.dumps(args['title'], ensure_ascii=False)
    return [style[kind + '_' + field].format_map(args) for field in ('group', 'title')
            if ('group_id' if field == 'group' else field) in values]


def display_values(values):
    return {key: value for key, value in values.items()
            if key == 'group_id' and value > 0 or key == 'title' and value.strip()}


def render_npc_initialization(npcs, profile=None):
    npcs = list(npcs)
    rooms = {(room['title'], room['limit']) for npc in npcs for room in npc.get('waitingrooms', [])}
    if any(not isinstance(title, str) or type(limit) is not int or not 0 <= limit <= 65535 for title, limit in rooms):
        raise ValueError('Invalid waitingroom metadata')
    variants = {json.dumps(values, sort_keys=True, ensure_ascii=False): values
                for npc in npcs if (values := display_values(metadata_values(npc)))}
    displays = []
    for npc in npcs:
        initial = npc.get('initial_display') or {}
        if player_class(initial.get('class_id',npc.get('class_id'))):
            displays.append((npc,initial or {'class_id':npc['class_id']}))
    if not variants and not rooms and not displays:
        return ''
    observed = {field: {values[field] for values in variants.values() if field in values}
                for field in ('group_id', 'title')}
    if variants and all(len(values) <= 1 for values in observed.values()):
        combined = {field: next(iter(values)) for field, values in observed.items() if values}
        variants = {json.dumps(combined, sort_keys=True, ensure_ascii=False): combined}
    style = templates(profile)
    lines = [style['oninit']]
    display_codes=list(dict.fromkeys(render_display(npc,display,style,require_full=True) for npc,display in displays))
    if len(display_codes)>1:
        lines.append(style['indent']+style['conflict'])
    for code in display_codes:
        if len(display_codes)>1: lines.append(style['indent']+style['block_open'].format_map({}))
        lines.append(style['indent']*(2 if len(display_codes)>1 else 1)+code)
        if len(display_codes)>1: lines.append(style['indent']+style['block_close'].format_map({}))
    conflict = len(variants) > 1
    if conflict:
        lines.append(style['indent'] + style['conflict'])
    for _, values in sorted(variants.items()):
        if conflict:
            lines.append(style['indent'] + style['block_open'].format_map({}))
        depth = style['indent'] * (2 if conflict else 1)
        lines.extend(depth + line for line in commands(values, 'npc', 0, style))
        if conflict:
            lines.append(style['indent'] + style['block_close'].format_map({}))
    if len(rooms) > 1:
        lines.append(style['indent'] + style['conflict'])
    for title, limit in sorted(rooms):
        if len(rooms) > 1:
            lines.append(style['indent'] + style['block_open'].format_map({}))
        lines.append(style['indent'] * (2 if len(rooms) > 1 else 1) +
                     style['waitingroom'].format(title=json.dumps(title, ensure_ascii=False), limit=limit))
        if len(rooms) > 1:
            lines.append(style['indent'] + style['block_close'].format_map({}))
    lines.append(style['indent'] + style['end'])
    result = '\n'.join(lines) + '\n'
    if len(result) > 4 * 1024 * 1024:
        raise ValueError('個体メタデータ出力が上限を超えています。')
    return result


def append_initialization(body, npcs, profile=None):
    initialization = render_npc_initialization(npcs, profile)
    if not initialization:
        return body
    # Dialogue rendering already emits close/end on its paths. Metadata must
    # not add another end merely because a switch/while ends with a brace.
    result = body.rstrip() + '\n\n' + initialization
    if len(result) > 4 * 1024 * 1024:
        raise ValueError('NPC本文と初期化が出力上限を超えています。')
    return result


def render_entity_metadata(data, profile=None):
    values = display_values(metadata_values(data))
    kind, actor = data['kind'], data['actor_id']
    if not values or kind not in ('NPC', 'MOB'):
        return '', {}
    style = templates(profile)
    context = style['npc_context' if kind == 'NPC' else 'mob_context'].format(
        actor_id=actor, actor_name=json.dumps(data.get('name', ''), ensure_ascii=False))
    body = (style['end'] + '\n\n' + render_npc_initialization([data], profile) if kind == 'NPC' else
            '\n'.join(commands(values, 'mob', actor, style)) + '\n')
    return context + '\n' + body.rstrip(), dict(actor_id=actor, entity_kind=kind, **values)


def build_metadata_report(entities):
    rows = []
    for entity in entities:
        text, values = render_entity_metadata(entity)
        if text:
            rows.append(dict(capture_session=entity['capture_session'], connection=entity['connection'],
                map_generation=entity['map_generation'], appearance=entity['appearance'],
                map_name=entity['map_name'], evidence=entity['metadata_evidence'], commands=text, **values))
    return rows


def render_packet_metadata(event, world):
    if event.direction != 'RECV' or event.packet_id not in (0xadf, 0x9ff, 0x9fe, 0x9fd):
        return '', {}
    try:
        actor = Reader(event.raw).number(2 if event.packet_id == 0xadf else 5, 'I')
    except ObservationError:
        return '', {}
    entity = world.find_current(event, 0, actor)
    if entity is None or (event.packet_id != 0xadf and entity.observations != 1):
        return '', {}
    data = dict(kind=entity.kind, actor_id=actor, name=entity.name, group_id=entity.group_id,
                title=entity.title, metadata_evidence=entity.metadata_evidence, field_issues=entity.field_issues)
    return render_entity_metadata(data)
