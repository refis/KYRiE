"""Replace observed self identity in script text and actor labels.

Keeps raw observation values unchanged. Substitution is render-time only for
logs and code candidates. Party/guild strings apply only when already known.
"""
from reconstruction.render_inputs import read_render_json, render_profile_size
import json
from pathlib import Path

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'identity_protection.json'
TEXT_KEYS = ('character_name', 'party_name', 'guild_name')
ACTOR_KEYS = ('actor_id', 'target_id', 'source_actor_id', 'unit_actor_id')


def _profile_path(path=None):
    from reconstruction.emulator_profiles import profile
    return Path(path) if path is not None else profile('identity_protection.json')


def templates(path=None):
    path = _profile_path(path)
    if render_profile_size(path) > 65536:
        raise ValueError('本人情報保護書式は64KiB以内にしてください。')
    result = read_render_json(path)
    if not isinstance(result, dict):
        raise ValueError('本人情報保護書式が不正です。')
    label = result.get('self_actor_label')
    fields = result.get('text_fields')
    expressions = result.get('expressions')
    actor_keys = result.get('actor_value_keys')
    if (not isinstance(label, str) or not 1 <= len(label) <= 32 or not label.isidentifier()
            or not isinstance(fields, list) or not fields or len(fields) > 16
            or any(field not in TEXT_KEYS for field in fields)
            or len(set(fields)) != len(fields)
            or not isinstance(expressions, dict) or set(expressions) != set(fields)
            or any(not isinstance(expressions[field], str) or not 1 <= len(expressions[field]) <= 64
                   for field in fields)
            or not isinstance(actor_keys, list) or not actor_keys or len(actor_keys) > 16
            or any(key not in ACTOR_KEYS for key in actor_keys) or len(set(actor_keys)) != len(actor_keys)):
        raise ValueError('本人情報保護書式の項目が不正です。')
    return dict(self_actor_label=label, text_fields=list(fields),
                expressions=dict(expressions), actor_value_keys=list(actor_keys))


def identity_from_player(state):
    if state is None:
        return {}
    result = {}
    for field in TEXT_KEYS:
        value = getattr(state, field, None)
        if isinstance(value, str) and value.strip():
            result[field] = value
    actor = getattr(state, 'actor_id', None)
    if type(actor) is int and actor > 0:
        result['actor_id'] = actor
    return result


def identity_for_connection(players, capture_session, connection):
    if players is None:
        return {}
    state = players.states.get((capture_session, connection))
    if state is None:
        state = players.states.get((0, connection))
    return identity_from_player(state)


def identity_from_store(players):
    """Best-effort identity for multi-conversation exports; prefer named states."""
    if players is None:
        return {}
    chosen = {}
    for state in players.states.values():
        identity = identity_from_player(state)
        if identity.get('character_name'):
            chosen = identity
        elif not chosen and identity:
            chosen = identity
    return chosen


def _replacements(identity, style):
    rows = []
    for field in style['text_fields']:
        value = identity.get(field)
        if isinstance(value, str) and value:
            rows.append((value, style['expressions'][field]))
    rows.sort(key=lambda row: (-len(row[0]), row[0], row[1]))
    return rows


def script_text(text, identity=None, profile=None):
    """Return a script expression: quoted literal and/or getstrcharinfo concatenations."""
    if not isinstance(text, str):
        raise ValueError('保護対象の文字列が不正です。')
    identity = identity or {}
    style = templates(profile)
    replacements = _replacements(identity, style)
    if not replacements:
        return json.dumps(text, ensure_ascii=False)
    parts = []
    index = 0
    while index < len(text):
        matched = None
        for value, expression in replacements:
            if text.startswith(value, index):
                matched = (value, expression)
                break
        if matched is None:
            if not parts or parts[-1][0] != 'lit':
                parts.append(['lit', text[index]])
            else:
                parts[-1][1] += text[index]
            index += 1
            continue
        parts.append(['expr', matched[1]])
        index += len(matched[0])
    return '+'.join(json.dumps(value, ensure_ascii=False) if kind == 'lit' else value
                    for kind, value in parts)


def protect_actor_value(value, identity=None, profile=None):
    identity = identity or {}
    self_id = identity.get('actor_id')
    if type(self_id) is not int or type(value) is not int or value != self_id:
        return value
    return templates(profile)['self_actor_label']


def apply_to_display_values(values, identity=None, profile=None):
    """Return display template values with protected text expressions and actor labels."""
    identity = identity or {}
    if not identity:
        return values
    style = templates(profile)
    result = dict(values)
    text = result.get('text')
    if isinstance(text, str):
        expression = script_text(text, identity, profile)
        if expression != json.dumps(text, ensure_ascii=False):
            result['text'] = expression
            result['_protect_text_text'] = True
    for key in style['actor_value_keys']:
        if key in result:
            result[key] = protect_actor_value(result[key], identity, profile)
    return result


def quote_text(text, identity=None, profile=None):
    """Quote helper for code generation: plain JSON string or protected expression."""
    return script_text(text, identity, profile)
