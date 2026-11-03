"""Manually adopted NPC timer labels; observed delays and trigger conditions are never inferred."""
from collections import Counter
from copy import deepcopy
import json
import math
import re
from pathlib import Path
from string import Formatter
from reconstruction.actor_appearance import VISUAL_FIELDS, render_display
from reconstruction.announcements import template_values as announcement_values
from reconstruction.event_trials import unassigned_in_scope
from reconstruction.instance_names import npc_name as base_npc_name

TIMER_PRESENTATION_KINDS = frozenset((
    'emotion', 'effect', 'effect_remove', 'announcement', 'unittalk', 'overhead',
    'effect_value', 'event_marker', 'hat_effect', 'colored_speech', 'classchange',
    'visibility_action', 'viewpoint', 'npc_display_action', 'progressbar', 'cutin',
    'mapcell'))
COMMENT_TIMER_KINDS = frozenset(
    ('effect_value', 'hat_effect', 'colored_speech', 'progressbar', 'cutin', 'mapcell'))
UNASSIGNED_TIMER_KINDS = frozenset(('announcement', 'cutin', 'mapcell'))
HIDE_TIMER_COMMANDS = frozenset(('hideonnpc', 'hideoffnpc'))
CLOAK_TIMER_COMMANDS = frozenset(('cloakonnpc', 'cloakoffnpc'))
VISIBILITY_TIMER_COMMANDS = HIDE_TIMER_COMMANDS | CLOAK_TIMER_COMMANDS

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'event_timers.json'
MAX_CONFIGURED_BYTES = 32 * 1024 * 1024
FIELDS = {'header': {'npc_name', 'map_name', 'trial'}, 'indent': set(), 'entry_end': set(),
          'label': {'time_ms'}, 'evidence': {'packet', 'observed_ms', 'manual_ms'},
          'emotion': {'value'}, 'effect': {'value'}, 'effect_remove': {'value'},
          'unittalk': {'text'}, 'overhead': {'text'},
          'effect_value': {'effect_id', 'value'},
          'event_marker': {'x', 'y', 'state', 'kind'},
          'hat_effect': {'enabled', 'effect_id'},
          'colored_speech': {'color_hex', 'text'},
          'progressbar': {'seconds', 'color_hex'},
          'cutin': {'image', 'position'},
          'mapcell': {'map_name', 'x', 'y', 'cell_type'},
          'classchange': {'target', 'class_id'},
          'visibility_action': {'command'},
          'viewpoint': {'kind', 'x', 'y', 'marker_id', 'color'},
          'npc_display_action': {'command'},
          'label_end': set()}
ANNOUNCEMENT_FIELDS = {'announcement': {'text', 'flag'},
    'announcement_styled': {'text', 'color', 'font_type', 'font_size', 'font_align', 'font_y'}}
FIELDS.update(ANNOUNCEMENT_FIELDS)
DEFAULT_FALLBACK_KEYS = (*ANNOUNCEMENT_FIELDS, 'effect_remove', 'unittalk', 'overhead',
                         'effect_value', 'event_marker', 'hat_effect', 'colored_speech', 'progressbar',
                         'cutin', 'mapcell', 'classchange', 'visibility_action', 'viewpoint',
                         'npc_display_action')


def _timer_profile(path=None):
    from reconstruction.emulator_profiles import profile
    return Path(path) if path is not None else profile('event_timers.json')


def load_timer_candidate(path, report, trial_index):
    """Restore manual times only when the full evidence and generated code match."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('タイマー設定JSONに重複キーがあります。')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('タイマー設定JSONに非有限数があります。')
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_CONFIGURED_BYTES + 1)
    if len(raw) > MAX_CONFIGURED_BYTES:
        raise ValueError('タイマー設定JSONは32MiB以内にしてください。')
    try:
        saved = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid_constant)
        if not isinstance(saved, dict):
            raise ValueError('対応するタイマー設定JSONではありません。')
        expected = validate_timer_candidate(saved, report, trial_index)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('タイマー設定JSONの文字コードまたは構造が不正です。') from exc
    return expected


def validate_timer_candidate(saved, report, trial_index):
    if not isinstance(saved, dict):
        raise ValueError('対応するタイマー設定JSONではありません。')
    expected = build_timer_candidate(report, trial_index, saved.get('manual_times_ms'), confirmed=True)
    def canonical(value):
        normalized = json.loads(json.dumps(value, allow_nan=False))
        return json.dumps(normalized, sort_keys=True, ensure_ascii=True, allow_nan=False)
    try:
        if canonical(saved) != canonical(expected):
            raise ValueError('対象NPC・試行・比較根拠・確認フラグ・生成コードが現在の候補と一致しません。')
    except (TypeError, RecursionError) as exc:
        raise ValueError('タイマー設定の構造が不正です。') from exc
    return expected


def render_timer_text(document, report, trial_index):
    checked = validate_timer_candidate(document, report, trial_index)
    # JSON escapes paths, names and newlines; only regenerated Auriga is executable.
    evidence = json.dumps(checked, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    text = '// ' + evidence + '\n' + checked['auriga']
    if len(text.encode('utf-8')) > MAX_CONFIGURED_BYTES:
        raise ValueError('根拠付きタイマーテキストは32MiB以内にしてください。')
    return text


def _validate_observation_fields(row):
    kind, fields = row['kind'], row['fields']
    if kind == 'announcement':
        announcement_values(fields)
        return
    if kind in ('unittalk', 'overhead'):
        if set(fields) != {'text'} or not isinstance(fields['text'], str) or len(fields['text']) > 65535:
            raise ValueError('ユニット／頭上メッセージの本文が不正です。')
        return
    if kind == 'effect_value':
        if (set(fields) != {'effect_id', 'value'}
                or any(type(fields[key]) is not int or not 0 <= fields[key] <= 2147483647
                       for key in ('effect_id', 'value'))):
            raise ValueError('値付きエフェクトの観測値が不正です。')
        return
    if kind == 'event_marker':
        if (set(fields) != {'x', 'y', 'state', 'kind'}
                or any(type(fields[key]) is not int or not 0 <= fields[key] <= 65535
                       for key in fields)):
            raise ValueError('イベントアイコンの観測値が不正です。')
        return
    if kind == 'hat_effect':
        if (set(fields) != {'enabled', 'effect_id'}
                or type(fields['enabled']) is not int or not 0 <= fields['enabled'] <= 255
                or type(fields['effect_id']) is not int or not 0 <= fields['effect_id'] <= 65535):
            raise ValueError('帽子エフェクトの観測値が不正です。')
        return
    if kind == 'colored_speech':
        if (set(fields) != {'color', 'text'}
                or type(fields['color']) is not int or not 0 <= fields['color'] <= 0xffffffff
                or not isinstance(fields['text'], str) or len(fields['text']) > 65535):
            raise ValueError('色付きユニット発言の観測値が不正です。')
        return
    if kind == 'progressbar':
        # Comment-only: keep observed seconds/color. Never treat seconds as OnTimer values.
        if (set(fields) != {'seconds', 'color'}
                or type(fields['seconds']) is not int or not 0 <= fields['seconds'] <= 2147483
                or type(fields['color']) is not int or not 0 <= fields['color'] <= 0xffffffff):
            raise ValueError('progressbarの観測値が不正です。コメント採用のみで待機命令へは変換しません。')
        return
    if kind == 'cutin':
        # Unassigned UI overlay: comment evidence only; ownership is not proven.
        if (set(fields) != {'image', 'position'}
                or not isinstance(fields['image'], str) or len(fields['image']) > 64
                or type(fields['position']) is not int or not 0 <= fields['position'] <= 255):
            raise ValueError('cutinの観測値が不正です。コメント採用のみで実行命令へは変換しません。')
        return
    if kind == 'mapcell':
        # Unassigned cell change: comment evidence only; never emit setcell.
        if (set(fields) != {'x', 'y', 'cell_type', 'map_name'}
                or any(type(fields[key]) is not int or not 0 <= fields[key] <= 65535
                       for key in ('x', 'y', 'cell_type'))
                or not isinstance(fields['map_name'], str) or not fields['map_name']
                or len(fields['map_name']) > 16):
            raise ValueError('mapcellの観測値が不正です。コメント採用のみで setcell へは変換しません。')
        return
    if kind == 'classchange':
        if (set(fields) != {'class_id', 'kind'}
                or type(fields['class_id']) is not int or not 0 <= fields['class_id'] <= 65535
                or type(fields['kind']) is not int or not 0 <= fields['kind'] <= 255):
            raise ValueError('外見変更の観測値が不正です。')
        return
    if kind == 'visibility_action':
        commands = fields.get('commands')
        previous = fields.get('previous_options')
        if (set(fields) != {'commands', 'target', 'options', 'previous_options'}
                or fields.get('target') is not None
                or not isinstance(commands, list) or not 1 <= len(commands) <= 2
                or not all(command in VISIBILITY_TIMER_COMMANDS for command in commands)
                or type(fields.get('options')) is not int or not 0 <= fields['options'] <= 0xffffffff
                or (previous is not None
                    and (type(previous) is not int or not 0 <= previous <= 0xffffffff))):
            raise ValueError(
                '表示状態変更の観測値が不正です。'
                '対象NPC自身の cloak、およびインスタンスマップ上の hide のみ採用できます。')
        # cloak*: self-originated packets reach only the viewing client — adoptable on any map.
        # hide*: adoptable only on instance maps, where delivery scope matches the script context.
        map_name = (row.get('npc') or {}).get('map_name') or ''
        if any(command in HIDE_TIMER_COMMANDS for command in commands) and '@' not in map_name:
            raise ValueError('hideonnpc／hideoffnpc はインスタンスマップ上の観測のみタイマー採用できます。')
        return
    if kind == 'viewpoint':
        # Same supported window as dialogue rendering: type 1/2, map coords, marker 0-255.
        if (set(fields) != {'kind', 'x', 'y', 'marker_id', 'color'}
                or fields.get('kind') not in (1, 2)
                or any(type(fields.get(key)) is not int or not 0 <= fields[key] <= 1023
                       for key in ('x', 'y'))
                or type(fields.get('marker_id')) is not int or not 0 <= fields['marker_id'] <= 255
                or type(fields.get('color')) is not int or not 0 <= fields['color'] <= 0xffffffff):
            raise ValueError(
                'viewpointの観測値が不正、またはタイマー採用可能な種別・座標範囲外です。'
                '未対応値はコメント保持のまま比較のみとしてください。')
        return
    if kind == 'npc_display_action':
        target = fields.get('target')
        display = fields.get('display')
        visual = display.get('appearance_data') if isinstance(display, dict) else None
        if (set(fields) != {'target', 'display', 'outside'}
                or not isinstance(target, dict)
                or not isinstance(target.get('name'), str) or not target['name']
                or not isinstance(target.get('map_name'), str) or not target['map_name']
                or type(fields.get('outside')) is not bool
                or not isinstance(display, dict)
                or type(display.get('class_id')) is not int or not 0 <= display['class_id'] <= 65535
                or set(display) - {'class_id', 'appearance_data'}
                or (visual is not None and (
                    not isinstance(visual, dict)
                    or any(type(visual.get(key)) is not int or not 0 <= visual[key] <= 65535
                           for key in VISUAL_FIELDS)))):
            raise ValueError('外見変更の観測値が不正です。対象NPC自身の setnpcdisplay のみ採用できます。')
        return
    value = fields.get('value')
    if type(value) is not int or not 0 <= value <= (255 if kind == 'emotion' else 2147483647):
        raise ValueError('演出IDが範囲外です。')


def validate_timer_trial(report, trial_index):
    """Shared entry guard for the editor and generator, including legacy reports."""
    if report.get('anchor_type', 'presentation') != 'presentation' or report.get('include_dialogue_actions'):
        raise ValueError('会話開始・マップ到着・会話アクションの比較は、NPCタイマーへの直接変換対象外です。演出基準点を選択してください。')
    if type(trial_index) is not int or not 0 <= trial_index < len(report['trials']):
        raise ValueError('採用する試行を選択してください。')
    trial = report['trials'][trial_index]
    if trial['quality_flags']:
        raise ValueError('品質除外された試行は採用できません。基準点・観測窓を見直してください。')
    if not 2 <= len(trial['events']) <= 200:
        raise ValueError('採用試行は基準点を含む2〜200演出に限定します。')
    for row in [trial['anchor'], *(event['observation'] for event in trial['events'])]:
        if row.get('anchor_type', 'presentation') != 'presentation' or row.get('comparison_scope'):
            raise ValueError('会話・MAP基準点や会話元を基準にした観測は、NPCタイマーへ直接採用できません。')
    unsupported = Counter(event['observation']['kind'] for event in trial['events']
                          if event['observation']['kind'] not in TIMER_PRESENTATION_KINDS)
    if unsupported:
        kinds = ' / '.join(f'{kind}: {count}件' for kind, count in sorted(unsupported.items()))
        raise ValueError(
            '未対応演出: '+kinds+'。この試行は比較のみです。'
            '対象NPC自身のエモーション・エフェクト・解除・announce・unittalk・overhead、'
            'イベントアイコンの showevent、外見変更の setnpcdisplay（01B0／会話外09xx含む）、'
            '表示状態の cloak（自身）、インスタンスマップ上の hide、対応範囲内の viewpoint、'
            'およびコメント採用の値付きエフェクト・帽子／色付き発言・progressbar・cutin・mapcell に対応しています。'
            'sound／music／progress_action／会話レイアウトは未対応です。')
    identity = report['npc_identity']
    if not identity.get('name') or not identity.get('map_name'):
        raise ValueError('対象NPCの名前とマップが必要です。')
    anchor = trial['anchor']
    def scope(row):
        npc = row.get('npc', {})
        return (row['capture_session'], row['flow_id'], row['actor_id'], npc.get('map_generation'), npc.get('appearance'))

    def related_unassigned(row, event):
        if (row.get('kind') not in UNASSIGNED_TIMER_KINDS
                or row.get('context') != 'outside_dialogue'
                or event.get('association_basis') != 'selected_timer_window_same_flow'
                or not unassigned_in_scope(row, anchor, UNASSIGNED_TIMER_KINDS)):
            return False
        # mapcell already requires exact target map + scene evidence in comparison;
        # re-check here so timer adoption cannot loosen that contract.
        if row['kind'] == 'mapcell':
            return (bool(row.get('map_context'))
                    and row['fields'].get('map_name') == (anchor.get('npc') or {}).get('map_name'))
        return True

    previous = -1
    if anchor.get('entity_kind') != 'NPC' or anchor.get('target_observed') is not True or anchor.get('context') != 'outside_dialogue':
        raise ValueError('対象NPCを観測した会話外の演出基準点が必要です。')
    for event in trial['events']:
        row, offset = event['observation'], event['offset_ms']
        if not related_unassigned(row, event) and (
                row.get('entity_kind') != 'NPC' or row.get('target_observed') is not True
                or row.get('context') != 'outside_dialogue' or scope(row) != scope(anchor)
                or any(row.get('npc', {}).get(key) != value for key, value in identity.items())):
            raise ValueError('演出の対象・配置・取得範囲が一致しません。')
        if type(row.get('packet_index')) is not int or row['packet_index'] < 0:
            raise ValueError('演出の根拠Packet番号がありません。')
        _validate_observation_fields(row)
        try:
            valid_offset = type(offset) in (int, float) and math.isfinite(offset) and offset >= previous
        except OverflowError:
            valid_offset = False
        if not valid_offset:
            raise ValueError('観測時間が不正です。')
        previous = offset
    return trial


def build_timer_candidate(report, trial_index, times_ms, *, confirmed=False, profile=None):
    trial = validate_timer_trial(report, trial_index)
    if confirmed is not True:
        raise ValueError('対象NPC・採用試行・全手入力時刻の確認が必要です。')
    events = trial['events']
    if not isinstance(times_ms, list) or len(times_ms) != len(events):
        raise ValueError('全演出の時刻を明示してください。')
    if any(type(value) is not int or not 1 <= value <= 2147483647 for value in times_ms):
        raise ValueError('時刻は1〜2147483647msの整数で指定してください。')
    if times_ms != sorted(times_ms):
        raise ValueError('時刻は観測順で同じか増える値にしてください。')
    identity = report['npc_identity']
    profile = _timer_profile(profile)
    templates = json.loads(Path(profile).read_text(encoding='utf-8'))
    if isinstance(templates, dict):
        defaults = json.loads(DEFAULT_PROFILE.read_text(encoding='utf-8'))
        for key in DEFAULT_FALLBACK_KEYS:
            templates.setdefault(key, defaults[key])
    if not isinstance(templates, dict) or set(templates) != set(FIELDS):
        raise ValueError('タイマー候補書式の項目が不正です。')
    for key, template in templates.items():
        if not isinstance(template, str) or len(template) > 16384:
            raise ValueError('タイマー候補書式が不正です。')
        for _, name, spec, conversion in Formatter().parse(template):
            if name is not None and (name not in FIELDS[key] or spec or conversion):
                raise ValueError('タイマー候補の書式引数が不正です。')
    if not 1 <= len(templates['indent']) <= 16 or any(c not in ' \t' for c in templates['indent']):
        raise ValueError('タイマー候補のインデントが不正です。')
    lines, size = [], 0
    def emit(key, indent=False, **values):
        nonlocal size
        text = templates[key].format_map(values)
        comment_only = all(line.startswith('//') and '\r' not in line for line in text.split('\n'))
        if key in ('header', 'evidence') or key in COMMENT_TIMER_KINDS:
            if not comment_only:
                raise ValueError('注意文・根拠・コメント採用演出の書式は全行コメントにしてください。')
        if key == 'label' and text != f'OnTimer{values["time_ms"]}:':
            raise ValueError('タイマーラベル書式が手入力時刻と一致しません。')
        if key in ('entry_end', 'label_end') and not re.fullmatch(r'end[ \t]*;', text):
            raise ValueError('タイマー候補の終端はend命令にしてください。')
        if key in ('emotion', 'effect', 'effect_remove') and not comment_only:
            command = {'emotion': 'emotion', 'effect': 'misceffect', 'effect_remove': 'delmisceffect'}[key]
            if not re.fullmatch(command + r'[ \t]+' + str(values['value']) + r'[ \t]*;', text):
                raise ValueError('演出書式の命令・IDが観測内容と一致しません。')
        if key == 'unittalk' and not comment_only and text != 'unittalk '+values['text']+';':
            raise ValueError('ユニット発言書式の命令・本文が観測内容と一致しません。')
        if key == 'overhead' and not comment_only and text != 'showmessage '+values['text']+';':
            raise ValueError('頭上メッセージ書式の命令・本文が観測内容と一致しません。')
        if key == 'classchange':
            if comment_only:
                raise ValueError('外見変更は setnpcdisplay 実行命令にしてください。')
            target = re.escape(values['target'])
            class_id = str(values['class_id'])
            auriga = rf'setnpcdisplay[ \t]+{target}[ \t]*,[ \t]*{class_id}[ \t]*;'
            rathena = rf'setnpcdisplay[ \t]*\([ \t]*{target}[ \t]*,[ \t]*{class_id}[ \t]*\)[ \t]*;'
            if not re.fullmatch(auriga, text) and not re.fullmatch(rathena, text):
                raise ValueError('外見変更書式の setnpcdisplay 対象・class が観測内容と一致しません。')
        if key == 'visibility_action':
            if comment_only:
                raise ValueError('表示状態変更は hide/cloak 実行命令にしてください。')
            command = values['command']
            if command not in VISIBILITY_TIMER_COMMANDS:
                raise ValueError('未対応の表示状態命令です。')
            if not re.fullmatch(re.escape(command) + r'[ \t]*;', text):
                raise ValueError('表示状態書式の hide/cloak 命令が観測内容と一致しません。')
        if key == 'viewpoint':
            if comment_only:
                raise ValueError('viewpointは実行命令にしてください。')
            expected = (rf'viewpoint[ \t]+{values["kind"]}[ \t]*,[ \t]*{values["x"]}[ \t]*,'
                        rf'[ \t]*{values["y"]}[ \t]*,[ \t]*{values["marker_id"]}[ \t]*,'
                        rf'[ \t]*{re.escape(values["color"])}[ \t]*;')
            if not re.fullmatch(expected, text):
                raise ValueError('viewpoint書式の種別・座標・色が観測内容と一致しません。')
        if key == 'event_marker' and not comment_only:
            # Self-form showevent; observed map coordinates stay in a trailing comment.
            expected = (rf'showevent[ \t]+{values["state"]}[ \t]*,[ \t]*{values["kind"]}[ \t]*;'
                        rf'[ \t]*//[ \t]*{values["x"]}[ \t]*,[ \t]*{values["y"]}[ \t]*')
            if not re.fullmatch(expected, text):
                raise ValueError('イベントアイコン書式の showevent が観測内容と一致しません。')
        if key == 'npc_display_action':
            if comment_only:
                raise ValueError('外見変更は setnpcdisplay 実行命令にしてください。')
            if text != values['command'] or not re.match(r'setnpcdisplay\b', text):
                raise ValueError('外見変更書式の setnpcdisplay が観測内容と一致しません。')
        for line in text.split('\n'):
            line = (templates['indent'] if indent else '') + line
            size += len(line) + 1
            if size > 4 * 1024 * 1024:
                raise ValueError('タイマー候補が出力上限を超えています。')
            lines.append(line)
    emit('header', npc_name=json.dumps(identity['name'], ensure_ascii=False),
         map_name=json.dumps(identity['map_name'], ensure_ascii=False), trial=trial_index + 1)
    emit('entry_end')
    previous_time = None
    for time, event in zip(times_ms, events):
        if time != previous_time:
            if previous_time is not None:
                emit('label_end', True)
            emit('label', time_ms=time)
        row = event['observation']
        emit('evidence', True, packet=row['packet_index'], observed_ms=event['offset_ms'], manual_ms=time)
        if row['kind'] == 'announcement':
            template, values = announcement_values(row['fields'])
            emit(template, True, **values)
        elif row['kind'] in ('unittalk', 'overhead'):
            emit(row['kind'], True, text=json.dumps(row['fields']['text'], ensure_ascii=False))
        elif row['kind'] == 'effect_value':
            emit('effect_value', True, effect_id=row['fields']['effect_id'], value=row['fields']['value'])
        elif row['kind'] == 'event_marker':
            emit('event_marker', True, **{key: row['fields'][key] for key in ('x', 'y', 'state', 'kind')})
        elif row['kind'] == 'hat_effect':
            emit('hat_effect', True, enabled=row['fields']['enabled'], effect_id=row['fields']['effect_id'])
        elif row['kind'] == 'colored_speech':
            emit('colored_speech', True, color_hex=f"{row['fields']['color']:08X}",
                 text=json.dumps(row['fields']['text'], ensure_ascii=False))
        elif row['kind'] == 'progressbar':
            emit('progressbar', True, seconds=row['fields']['seconds'],
                 color_hex=f"{row['fields']['color'] & 0xffffff:06X}")
        elif row['kind'] == 'cutin':
            emit('cutin', True, image=json.dumps(row['fields']['image'], ensure_ascii=False),
                 position=row['fields']['position'])
        elif row['kind'] == 'mapcell':
            emit('mapcell', True, map_name=json.dumps(row['fields']['map_name'], ensure_ascii=False),
                 x=row['fields']['x'], y=row['fields']['y'], cell_type=row['fields']['cell_type'])
        elif row['kind'] == 'classchange':
            target = json.dumps(base_npc_name(identity['name'], identity.get('map_name')),
                                ensure_ascii=False)
            if '@' in (identity.get('map_name') or ''):
                target = 'getmdnpcname(' + target + ')'
            emit('classchange', True, target=target, class_id=row['fields']['class_id'])
        elif row['kind'] == 'visibility_action':
            if row['fields'].get('target') is not None:
                raise ValueError('タイマー候補の表示状態変更は対象NPC自身のみです。')
            for command in row['fields']['commands']:
                emit('visibility_action', True, command=command)
        elif row['kind'] == 'viewpoint':
            fields = row['fields']
            emit('viewpoint', True, kind=fields['kind'], x=fields['x'], y=fields['y'],
                 marker_id=fields['marker_id'], color=f'0x{fields["color"] & 0xffffff:06X}')
        elif row['kind'] == 'npc_display_action':
            target = row['fields'].get('target') or {}
            if (base_npc_name(target.get('name'), target.get('map_name'))
                    != base_npc_name(identity['name'], identity.get('map_name'))
                    or target.get('map_name') != identity.get('map_name')):
                raise ValueError('タイマー候補の外見変更は対象NPC自身のみです。')
            dialogue_templates = json.loads((Path(profile).parent / 'dialogue.json').read_text(encoding='utf-8'))
            command = render_display(dict(name=identity['name'], map_name=identity['map_name']),
                                     row['fields']['display'], dialogue_templates, outside=False)
            unknown = dialogue_templates.get('npc_display_unknown')
            if (not isinstance(command, str) or not command or command == unknown
                    or command.lstrip().startswith('//') or not command.startswith('setnpcdisplay')):
                raise ValueError('外見変更の setnpcdisplay を生成できません。')
            emit('npc_display_action', True, command=command)
        else:
            emit(row['kind'], True, value=row['fields']['value'])
        previous_time = time
    emit('label_end', True)
    return dict(schema_version=1, kind='event_timer_candidate', trial_index=trial_index,
        target_npc=deepcopy(identity), manual_times_ms=list(times_ms), setting_origin='manual_review',
        adoption_confirmed=True, cause_confirmed=False, server_timer_confirmed=False,
        automatic_start_generated=False, auriga='\n'.join(lines) + '\n', source_report=deepcopy(report))
