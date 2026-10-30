"""Comment-only Auriga placement candidates; visibility is never spawn configuration."""
from copy import deepcopy
import json
import re
from pathlib import Path
from string import Formatter

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'mob_spawns.json'
CONFIGURED_PROFILE = DEFAULT_PROFILE.with_name('mob_spawn_configured.json')
PLACEMENT_FIELDS = ('map_name', 'x', 'y', 'xs', 'ys', 'mob_name', 'class_id',
                    'amount', 'delay1', 'delay2', 'event')
TEMPLATE_FIELDS = {'header': set(), 'quality': {'count', 'issues', 'saturated', 'transport'},
    'scope': {'capture', 'connection', 'generation'}, 'candidate': set(PLACEMENT_FIELDS),
    'evidence': {'json'}, 'incomplete': {'fields'}}

MAX_CONFIGURED_BYTES = 8 * 1024 * 1024


def validate_configured(saved, candidate, source_sessions=None):
    if (not isinstance(saved, dict) or type(saved.get('schema_version')) is not int
            or saved.get('schema_version') != 1 or saved.get('configured_values_confirmed') is not True
            or saved.get('active_placement_generated') is not True
            or saved.get('setting_origin') != 'manual_review'):
        raise ValueError('確認済みMOB配置設定JSONではありません。')
    expected = configure_candidate(candidate, saved.get('placement_fields'), confirmed=True,
                                   source_sessions=source_sessions)
    def canonical(value):
        try:
            return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError('配置設定の構造が不正です。') from exc
    # JSON converts integer session keys to strings. Normalize without changing evidence.
    normalized = json.loads(json.dumps(expected, allow_nan=False))
    if canonical(saved) != canonical(normalized):
        raise ValueError('配置設定の観測根拠・出典・配置行・書式が現在の候補と一致しません。')
    return expected


def load_configured(path, candidate, source_sessions=None):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('配置設定JSONに重複キーがあります。')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('配置設定JSONに非有限数があります。')
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_CONFIGURED_BYTES + 1)
    if len(raw) > MAX_CONFIGURED_BYTES:
        raise ValueError('配置設定JSONは8MiB以内にしてください。')
    try:
        saved = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('配置設定JSONの文字コードまたは構造が不正です。') from exc
    return validate_configured(saved, candidate, source_sessions)


def render_configured(document, candidate, source_sessions=None):
    checked = validate_configured(json.loads(json.dumps(document, allow_nan=False)), candidate, source_sessions)
    evidence = json.dumps(dict(observation=checked['observation'], source_sessions=checked['source_sessions']),
                          ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    text = checked['review_header'] + '\n// ' + evidence + '\n' + checked['placement_row'] + '\n'
    if len(text.encode('utf-8')) > MAX_CONFIGURED_BYTES:
        raise ValueError('配置テキストは8MiB以内にしてください。')
    return text


def configure_candidate(candidate, fields, *, confirmed=False, source_sessions=None,
                        profile=CONFIGURED_PROFILE):
    if confirmed is not True:
        raise ValueError('対象DBと配置設定の確認が必要です。')
    if not isinstance(fields, dict) or set(fields) != set(PLACEMENT_FIELDS):
        raise ValueError('全配置項目を明示してください。')
    values = {}
    for key in PLACEMENT_FIELDS:
        value = fields[key]
        if type(value) not in (str, int):
            raise ValueError(f'{key}: 値を指定してください。')
        if key == 'map_name':
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_@.-]{1,23}', value):
                raise ValueError('マップ名は英数字・_@.-の23文字以内で指定してください。')
        elif key == 'mob_name':
            if (not isinstance(value, str) or not value.strip() or
                    any(char in ',;{}"/\\' or ord(char) < 32 or ord(char) == 127
                        or (char.isspace() and char != ' ') for char in value)):
                raise ValueError('MOB名が空、または配置宣言に使えない文字を含んでいます。')
            try:
                if len(value.encode('cp932')) > 23:
                    raise ValueError('MOB名はCP932で23bytes以内にしてください。')
            except UnicodeEncodeError as exc:
                raise ValueError('MOB名をCP932で表現できません。') from exc
        elif key == 'event':
            if not isinstance(value, str) or (value and not re.fullmatch(
                    r'[A-Za-z_][A-Za-z0-9_]*::On[A-Za-z0-9_]+', value)) or len(value) > 76:
                raise ValueError('イベントは空欄またはNPC名::Onラベル（76文字以内）で指定してください。')
        else:
            if not re.fullmatch(r'[0-9]{1,10}', str(value)):
                raise ValueError(f'{key}: 非負の整数を指定してください。')
            value = int(value)
            low, high = (0, 1023)
            if key == 'class_id':
                low, high = 1, 65535
            elif key == 'amount':
                low, high = 1, 1000
            elif key in ('delay1', 'delay2'):
                low, high = 0, 2147483647
            if not low <= value <= high:
                raise ValueError(f'{key}: {low}〜{high}で指定してください。')
        values[key] = value
    if values['delay1'] + values['delay2'] > 2147483647:
        raise ValueError('delay1とdelay2の合計は2147483647以内にしてください。')
    templates = json.loads(Path(profile).read_text(encoding='utf-8'))
    if not isinstance(templates, dict) or set(templates) != {'header', 'placement'}:
        raise ValueError('配置出力の書式項目が不正です。')
    for key, template in templates.items():
        if not isinstance(template, str) or not template or len(template) > 65536:
            raise ValueError('配置出力の書式が不正です。')
        for _, name, spec, conversion in Formatter().parse(template):
            if name is not None and (key != 'placement' or name not in PLACEMENT_FIELDS or spec or conversion):
                raise ValueError('配置出力の書式引数が不正です。')
    header = templates['header']
    if any(not line.startswith('//') for line in header.splitlines()):
        raise ValueError('配置出力の注意文は全行コメントにしてください。')
    row = templates['placement'].format_map(values)
    expected = ('{map_name},{x},{y},{xs},{ys}\tmonster\t{mob_name}\t'
                '{class_id},{amount},{delay1},{delay2},{event}').format_map(values)
    if row != expected:
        raise ValueError('配置書式の列順・区切りがAuriga形式と一致しません。')
    return dict(schema_version=1, placement_fields=values, placement_row=row, review_header=header,
                setting_origin='manual_review', configured_values_confirmed=True,
                active_placement_generated=True, observation=deepcopy(candidate),
                source_sessions=deepcopy(source_sessions or {}))


def build_candidates(snapshot, source_sessions=None):
    buckets = {}
    for appearance in snapshot['appearances']:
        key = (appearance['capture_session'], appearance['connection'],
               appearance['map_generation'], appearance['class_id'])
        buckets.setdefault(key, []).append(appearance)
    candidates = []
    for group in snapshot['groups']:
        key = (group['capture_session'], group['connection'], group['map_generation'], group['class_id'])
        values = dict.fromkeys(PLACEMENT_FIELDS)
        values.update(map_name=group['map_name'], class_id=group['class_id'])
        # Even 09FE and a unique coordinate do not establish a fixed spawn point.
        candidates.append(dict(scope=dict(zip(('capture_session', 'connection', 'map_generation'), key[:3])),
            placement_fields=values, requires_edit=[name for name in PLACEMENT_FIELDS if values[name] is None],
            observed=deepcopy(group), appearances=deepcopy(buckets.get(key, [])),
            configured_values_confirmed=False, active_placement_generated=False))
    return dict(schema_version=1, candidates=candidates, source_sessions=deepcopy(source_sessions or {}),
                world_issue_count=snapshot['world_issue_count'], saturated=snapshot['saturated'],
                transport_quality=snapshot['transport_quality'], active_placements_generated=False)


def render_candidates(report, profile=DEFAULT_PROFILE):
    templates = json.loads(Path(profile).read_text(encoding='utf-8'))
    if not isinstance(templates, dict) or set(templates) != set(TEMPLATE_FIELDS):
        raise ValueError('MOB配置候補の書式項目が不正です。')
    for key, template in templates.items():
        if not isinstance(template, str) or len(template) > 65536:
            raise ValueError('MOB配置候補の書式が不正です。')
        for _, name, spec, conversion in Formatter().parse(template):
            if name is not None and (name not in TEMPLATE_FIELDS[key] or spec or conversion):
                raise ValueError('MOB配置候補の書式引数が不正です。')
    lines, size = [], 0
    def emit(key, **values):
        nonlocal size
        for line in templates[key].format_map(values).splitlines():
            if not line.startswith('//'):
                raise ValueError('MOB配置候補は全行コメントにしてください。')
            size += len(line) + 1
            if size > 4 * 1024 * 1024:
                raise ValueError('MOB配置候補が出力上限を超えています。')
            lines.append(line)
    def safe(value):
        if value is None:
            return '?'
        # Keep external names and source paths from introducing declarations or columns.
        return json.dumps(value, ensure_ascii=True) if isinstance(value, str) else str(value)
    emit('header')
    emit('quality', count=len(report['candidates']), issues=report['world_issue_count'],
         saturated=report['saturated'], transport=report['transport_quality'])
    for candidate in report['candidates']:
        values = candidate['placement_fields']
        scope = candidate['scope']
        emit('scope', capture=scope['capture_session'], connection=safe(scope['connection']),
             generation=scope['map_generation'])
        # ? explicitly marks unknowns; this comment is a worksheet, never an active declaration.
        cell = {key: (value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_@.-]{1,32}', value)
                      else safe(value)) for key, value in values.items()}
        emit('candidate', **cell)
        evidence = dict(observed=candidate['observed'], appearances=candidate['appearances'],
                        source_ref=report['source_sessions'].get(str(scope['capture_session']),
                            report['source_sessions'].get(scope['capture_session'])))
        emit('evidence', json=json.dumps(evidence, ensure_ascii=True, separators=(',', ':')))
        emit('incomplete', fields=','.join(candidate['requires_edit']))
    return '\n'.join(lines) + '\n'
