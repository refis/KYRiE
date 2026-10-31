"""DB review candidates and explicit manual settings, separate from observations."""
from copy import deepcopy
import json
from pathlib import Path
from string import Formatter
import re

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'mob_skills.json'


def _mob_skill_profile(path=None, configured=False):
    from reconstruction.emulator_profiles import profile
    name = 'mob_skill_configured.json' if configured else 'mob_skills.json'
    return Path(path) if path is not None else profile(name)


CONFIGURED_PROFILE = DEFAULT_PROFILE.with_name('mob_skill_configured.json')
COLUMNS = ('MOB_ID', 'NAME', 'STATE', 'SKILL_ID', 'SKILL_LV', 'RATE', 'CASTTIME', 'DELAY',
           'CANCEL', 'TARGET', 'CONDITION', 'CONDITION_VALUE', 'VAL1', 'VAL2', 'VAL3', 'VAL4',
           'VAL5', 'VAL6', 'EMOTION')
FIELDS = {'header': set(), 'columns': set(), 'candidate': {'row'},
          'quality': {'count', 'issues', 'unattributed', 'saturated'},
          'evidence': {'appearances', 'raw_levels', 'cast_ms', 'observed_intervals'}, 'incomplete': {'fields'},
          'name': {'monster_name','skill_name'}, 'unknown_monster': {'mob_id'}, 'unknown_skill': {'skill_id'}}


STATUS_CONDITIONS = tuple(f'{who}status{mode}' for who in ('my', 'friend', 'target', 'master')
                          for mode in ('on', 'off'))
STATUS_VALUES = ('anybad', 'stone', 'freeze', 'stun', 'sleep', 'poison', 'curse',
                 'silence', 'confusion', 'blind', 'hiding', 'sight', 'lexaeterna')
NUMERIC_CONDITIONS = ('always', 'myhpltmaxrate', 'myhpgtmaxrate', 'friendhpltmaxrate',
    'friendhpgtmaxrate', 'attackpcgt', 'attackpcge', 'slavelt', 'slavele',
    'closedattacked', 'longrangeattacked', 'skillused', 'casttargeted', 'afterskill',
    'targethpgtmaxrate', 'targethpltmaxrate', 'targethpgt', 'targethplt',
    'masterhpgtmaxrate', 'masterhpltmaxrate', 'masterattacked', 'areaslavegt',
    'areaslavele', 'rudeattacked', 'onspawn')

MANUAL_CHOICES = {
    'STATE': ('any', 'idle', 'walk', 'attack', 'dead', 'loot', 'chase', 'command', 'angry', 'follow'),
    'CANCEL': ('yes', 'no'),
    'TARGET': ('target', 'self', 'friend', 'master', 'slave', 'around',
               *(f'around{i}' for i in range(1, 9))),
    'CONDITION': NUMERIC_CONDITIONS + STATUS_CONDITIONS,
}


VAL_KEYS = frozenset(f'VAL{i}' for i in range(1, 7))


def valid_db_name(value):
    return (isinstance(value,str) and 1 <= len(value) <= 256 and bool(value.strip())
            and value != 'clear' and ',' not in value and '//' not in value
            and all(char.isprintable() for char in value))


def valid_val_token(value):
    """CSV-safe Auriga-style VAL token: explicit string, never inferred from observations."""
    return (isinstance(value, str) and 1 <= len(value) <= 64 and value == value.strip()
            and ',' not in value and '//' not in value
            and all(char.isprintable() and not char.isspace() for char in value))


def load_templates(profile=None):
    templates = json.loads(_mob_skill_profile(profile).read_text(encoding='utf-8'))
    defaults = {'name':'{monster_name}＠{skill_name}', 'unknown_monster':'MOB_ID_{mob_id}', 'unknown_skill':'SKILL_ID_{skill_id}'}
    if not isinstance(templates,dict):
        raise ValueError('MOBスキル候補の書式が不正です。')
    for key,value in defaults.items():
        templates.setdefault(key,value)
    if set(templates) != set(FIELDS):
        raise ValueError('MOBスキル候補の書式が不正です。')
    for key,value in templates.items():
        if not isinstance(value,str) or len(value)>65536:
            raise ValueError('MOBスキル候補の書式が不正です。')
        for _,name,spec,conversion in Formatter().parse(value):
            if name is not None and (name not in FIELDS[key] or spec or conversion):
                raise ValueError('MOBスキル候補の書式引数が不正です。')
    return templates


def configure_candidate(candidate, fields, *, confirmed=False, source_sessions=None):
    """Validate an explicitly reviewed, numeric-parameter subset of Auriga rows."""
    if confirmed is not True:
        raise ValueError('対象DBと全設定値の確認が必要です。')
    if not isinstance(fields, dict) or set(fields) != set(COLUMNS):
        raise ValueError('19列すべてを指定してください。')
    values = {}
    for key in COLUMNS:
        value = fields[key]
        if type(value) not in (str, int):
            raise ValueError(f'{key}: 値を入力してください。')
        value = str(value)
        if key in MANUAL_CHOICES:
            if value not in MANUAL_CHOICES[key]:
                raise ValueError(f'{key}: 未対応の設定値です。')
        elif key == 'NAME':
            if not valid_db_name(value):
                raise ValueError('NAME: 256文字以内。カンマ・改行・制御文字・//・clearは禁止です。')
        elif key == 'CONDITION_VALUE' and fields['CONDITION'] in STATUS_CONDITIONS:
            if value not in STATUS_VALUES:
                raise ValueError('CONDITION_VALUE: 状態条件には対応する状態名を指定してください。')
        elif key in VAL_KEYS and not re.fullmatch(r'-?[0-9]{1,10}', value):
            if not valid_val_token(value):
                raise ValueError(f'{key}: 整数、またはカンマ・空白・//を含まない64文字以内の文字列を入力してください。')
        else:
            if not re.fullmatch(r'-?[0-9]{1,10}', value):
                raise ValueError(f'{key}: 整数を入力してください。')
            value = int(value)
            low, high = -2147483648, 2147483647
            if key in ('MOB_ID', 'SKILL_ID', 'SKILL_LV'):
                low, high = 1, 32767 if key == 'SKILL_LV' else 65535
            elif key == 'RATE':
                low, high = 0, 10000
            elif key in ('CASTTIME', 'DELAY'):
                low = 0
            elif key == 'CONDITION_VALUE':
                low, high = (-32768, 32767) if fields['CONDITION'] != 'always' else (0, 0)
            if not low <= value <= high:
                raise ValueError(f'{key}: {low}〜{high}の範囲で指定してください。')
        values[key] = value
    parts = [str(values[key]) for key in COLUMNS]
    # Auriga ignores a one-character EMOTION token (strlen > 1).
    if 0 <= values['EMOTION'] <= 9:
        parts[-1] = f"{values['EMOTION']:02d}"
    row = ','.join(parts)
    if len(row.encode('utf-8')) > 1018:
        raise ValueError('DB行が長すぎます。')
    return dict(schema_version=1, db_fields=values, db_row=row,
                configured_values_confirmed=True, active_db_row_generated=True,
                setting_origin='manual_review', observation=deepcopy(candidate),
                source_sessions=deepcopy(source_sessions or {}))


MAX_CONFIGURED_BYTES = 8 * 1024 * 1024


def load_configured(path, candidate, source_sessions=None):
    """Resume only settings bound to the same observation and source references."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('設定JSONに重複キーがあります。')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('設定JSONに非有限数があります。')

    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_CONFIGURED_BYTES + 1)
    if len(raw) > MAX_CONFIGURED_BYTES:
        raise ValueError('設定JSONは8MiB以内にしてください。')
    try:
        saved = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                           parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('設定JSONの文字コードまたは構造が不正です。') from exc
    return validate_configured(saved, candidate, source_sessions)


def validate_configured(saved, candidate, source_sessions=None):
    """Validate the full saved envelope against its selected evidence."""
    keys = {'schema_version', 'db_fields', 'db_row', 'configured_values_confirmed',
            'active_db_row_generated', 'setting_origin', 'observation', 'source_sessions'}
    if (not isinstance(saved, dict) or set(saved) != keys or
            type(saved['schema_version']) is not int or saved['schema_version'] != 1 or
            saved['configured_values_confirmed'] is not True or
            saved['active_db_row_generated'] is not True or saved['setting_origin'] != 'manual_review'):
        raise ValueError('対応する確認済みMOBスキル設定JSONではありません。')
    # JSON roundtrip normalizes integer dictionary keys without mutating evidence.
    expected_observation = json.loads(json.dumps(candidate, allow_nan=False))
    expected_sources = json.loads(json.dumps(source_sessions or {}, allow_nan=False))
    def canonical(value):
        try:
            return json.dumps(value, sort_keys=True, allow_nan=False)
        except RecursionError as exc:
            raise ValueError('設定JSONの構造が深すぎます。') from exc
    observed = deepcopy(saved['observation'])
    if (isinstance(observed,dict) and isinstance(observed.get('db_fields'),dict)
            and observed['db_fields'].get('NAME') == f"observed_{candidate['class_id']}_{candidate['skill_id']}"):
        observed['db_fields']['NAME'] = expected_observation['db_fields']['NAME']
        if isinstance(observed.get('requires_edit'),list):
            observed['requires_edit'] = [key for key in COLUMNS if key in observed['requires_edit'] or
                                       key == 'NAME' and expected_observation['db_fields']['NAME'] is None]
    if (canonical(observed) != canonical(expected_observation) or
            canonical(saved['source_sessions']) != canonical(expected_sources)):
        raise ValueError('選択中の観測根拠・ログ出典と一致しない設定です。')
    checked = configure_candidate(candidate, saved['db_fields'], confirmed=True,
                                  source_sessions=source_sessions)
    legacy_row = ','.join(str(checked['db_fields'][key]) for key in COLUMNS)
    if saved['db_row'] not in (checked['db_row'], legacy_row):
        raise ValueError('DB行と設定値が一致しません。')
    return checked


def render_configured(document, profile=None):
    """One active DB row followed by bounded comment lines containing its evidence."""
    if not isinstance(document, dict):
        raise ValueError('設定JSONが不正です。')
    checked = validate_configured(document, document.get('observation'), document.get('source_sessions'))
    evidence = json.dumps(checked, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    if len(evidence.encode('ascii')) > MAX_CONFIGURED_BYTES:
        raise ValueError('設定・観測根拠が8MiBを超えています。')
    templates = json.loads(_mob_skill_profile(profile, configured=True).read_text(encoding='utf-8'))
    if not isinstance(templates, dict) or set(templates) != {'header', 'evidence_header'}:
        raise ValueError('確認済みDB行の書式が不正です。')
    def comment_lines(key):
        value = templates[key]
        if not isinstance(value, str) or not value or len(value) > 65536:
            raise ValueError('確認済みDB行の書式が不正です。')
        lines = value.split('\n')
        if any(not line.startswith('//') or len(line.encode('utf-8')) > 900 or
               any(ord(char) < 32 for char in line) for line in lines):
            raise ValueError('説明書式は900bytes以内のコメント行にしてください。')
        return lines
    lines = comment_lines('header') + ['// ' + ','.join(COLUMNS), checked['db_row']]
    lines += comment_lines('evidence_header')
    # ASCII-escaped JSON avoids line/control injection and encoding loss in provenance.
    # Keep each physical line below Auriga's 1024-byte reader buffer.
    lines += ['// ' + evidence[index:index + 180] for index in range(0, len(evidence), 180)]
    return '\n'.join(lines) + '\n'


def build_candidates(snapshot, names=None, source_sessions=None, *, profile=None):
    names = names or {}
    templates = load_templates(profile)
    monster_names = {}
    for observation in snapshot.get('observations', []):
        name = observation.get('name')
        if isinstance(name,str) and name.strip():
            monster_names.setdefault(observation.get('class_id'),set()).add(name)
    individuals = {}
    for row in snapshot['individual_skills']:
        individuals.setdefault((row['class_id'], row['skill_id']), []).append(deepcopy(row))
    result = []
    for row in snapshot['class_skills']:
        mob_id, skill_id = row['class_id'], row['skill_id']
        if type(mob_id) is not int or mob_id <= 0 or type(skill_id) is not int or skill_id <= 0:
            continue
        values = dict.fromkeys(COLUMNS)
        observed_names = monster_names.get(mob_id,set())
        monster_name = next(iter(observed_names)) if len(observed_names)==1 else templates['unknown_monster'].format(mob_id=mob_id)
        skill_name = names.get(skill_id,names.get(str(skill_id))) or templates['unknown_skill'].format(skill_id=skill_id)
        db_name = templates['name'].format(monster_name=monster_name,skill_name=skill_name)
        values.update(MOB_ID=mob_id, NAME=db_name if valid_db_name(db_name) else None, SKILL_ID=skill_id)
        if len(row['known_levels']) == 1 and not row['unknown_level_notifications'] and not row['issue_notifications']:
            values['SKILL_LV'] = row['known_levels'][0]
        result.append(dict(class_id=mob_id, skill_id=skill_id,
            skill_name=names.get(skill_id, names.get(str(skill_id))), db_fields=values,
            requires_edit=[key for key in COLUMNS if values[key] is None],
            observed=deepcopy(row), individuals=individuals.get((mob_id, skill_id), []),
            configured_values_confirmed=False, active_db_row_generated=False))
    return dict(schema_version=1, columns=list(COLUMNS), candidates=result,
        source_sessions=dict(source_sessions or {}), issue_count=snapshot['issue_count'],
        saturated=snapshot['saturated'], unattributed_notifications=snapshot['unattributed_notifications'],
        transport_quality=snapshot['transport_quality'], active_db_rows_generated=False)


def render_candidates(report, profile=None):
    templates = load_templates(profile)
    lines, output_chars = [], 0
    def emit(key, **values):
        nonlocal output_chars
        for line in templates[key].format_map(values).splitlines():
            if not line.startswith('//'):
                raise ValueError('MOBスキル候補は全行コメント形式にしてください。')
            output_chars += len(line) + 1
            if output_chars > 4 * 1024 * 1024:
                raise ValueError('MOBスキル候補が出力上限を超えています。')
            lines.append(line)
    emit('header')
    emit('quality', count=len(report['candidates']), issues=report['issue_count'],
         unattributed=report['unattributed_notifications'], saturated=report['saturated'])
    emit('columns')
    for candidate in report['candidates']:
        values = candidate['db_fields']
        emit('candidate', row=','.join('?' if values[key] is None else str(values[key]) for key in COLUMNS))
        observed = candidate['observed']
        intervals = {key: value['min_ms'] for key, value in observed['intervals'].items()}
        emit('evidence', appearances=observed['source_appearances'], raw_levels=observed['raw_levels'],
             cast_ms=observed['cast_ms'], observed_intervals=json.dumps(intervals, sort_keys=True))
        emit('incomplete', fields=','.join(candidate['requires_edit']))
    output = '\n'.join(lines) + '\n'
    if len(output) > 4 * 1024 * 1024:
        raise ValueError('MOBスキル候補が出力上限を超えています。')
    return output
