"""Explicit packet-structure overlays for unknown or extended IDs.

Length and display field layouts are applied only when loaded. Index tags annotate
display values from existing catalogs / WorldStore; they never invent names or
resync framing after an unknown ID.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from parser.display import TYPES, _unique_object
from reconstruction.client_names import item_name, map_label, quest_label
from reconstruction.reference_names import reference_labels
from reconstruction.skills import load_skill_names

INDEX_TAGS = frozenset({
    'actor_id', 'item_id', 'quest_id', 'map_name', 'class_id',
    'skill_id', 'status_icon', 'visual_effect',
})
MAX_OVERLAY_BYTES = 512 * 1024
MAX_PACKETS = 4096
ID_PATTERN = re.compile(r'(?:0x)?[0-9a-fA-F]{1,4}')


class OverlayError(ValueError):
    pass


def _integer(value, label, minimum=None, maximum=None):
    if type(value) is not int:
        raise OverlayError(f'{label}: expected integer')
    if minimum is not None and value < minimum:
        raise OverlayError(f'{label}: below minimum {minimum}')
    if maximum is not None and value > maximum:
        raise OverlayError(f'{label}: above maximum {maximum}')


def _parse_id(value, label):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and ID_PATTERN.fullmatch(value):
        number = int(value, 16)
    else:
        raise OverlayError(f'{label}: expected hex packet id')
    if not 0 <= number <= 65535:
        raise OverlayError(f'{label}: packet id out of range')
    return number


def _validate_field(name, spec, encoding='cp932'):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
        raise OverlayError(f'Invalid field name: {name}')
    if not isinstance(spec, dict) or set(spec) - {'offset', 'type', 'length', 'encoding', 'scale', 'add', 'mask', 'index'}:
        raise OverlayError(f'{name}: invalid field keys')
    _integer(spec.get('offset'), name + '.offset', 0, 65535)
    kind = spec.get('type')
    if kind not in (*TYPES, 'string', 'bytes'):
        raise OverlayError(f'{name}: unknown type')
    if 'index' in spec:
        if not isinstance(spec['index'], str) or spec['index'] not in INDEX_TAGS:
            raise OverlayError(f'{name}: unknown index tag')
    if kind in ('string', 'bytes'):
        if 'length' in spec:
            _integer(spec['length'], name + '.length', 0, 65535)
        if set(spec) & {'scale', 'add', 'mask'}:
            raise OverlayError(f'{name}: numeric transforms require an integer field')
    else:
        if 'length' in spec or 'encoding' in spec:
            raise OverlayError(f'{name}: integer fields cannot specify length/encoding')
        for option in ('scale', 'add', 'mask'):
            if option in spec:
                _integer(spec[option], name + '.' + option, -2**64, 2**64)


def load_overlay(path):
    path = Path(path)
    if path.stat().st_size > MAX_OVERLAY_BYTES:
        raise OverlayError('Packet overlay exceeds size limit')
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverlayError(f'Invalid overlay JSON: {exc}') from exc
    validate_overlay(document)
    document['_sha256'] = hashlib.sha256(raw).hexdigest()
    document['_path'] = str(path.resolve())
    return document


def validate_overlay(document):
    if not isinstance(document, dict) or type(document.get('version')) is not int or document['version'] != 1:
        raise OverlayError('Unsupported overlay version')
    if set(document) - {'version', 'packets', 'note', '_sha256', '_path'}:
        raise OverlayError('Unknown overlay keys')
    if 'note' in document and (not isinstance(document['note'], str) or len(document['note']) > 4096):
        raise OverlayError('note must be a short string')
    packets = document.get('packets')
    if not isinstance(packets, list) or not packets or len(packets) > MAX_PACKETS:
        raise OverlayError('packets must be a nonempty bounded list')
    seen = set()
    for row in packets:
        if not isinstance(row, dict) or set(row) - {'id', 'length', 'name', 'fields', 'template', 'min_length', 'note'}:
            raise OverlayError('Invalid overlay packet object')
        pid = _parse_id(row.get('id'), 'id')
        if pid in seen:
            raise OverlayError(f'Duplicate overlay packet id: 0x{pid:04X}')
        seen.add(pid)
        length = row.get('length')
        _integer(length, 'length')
        if length != -1 and not 2 <= length <= 65535:
            raise OverlayError('length must be -1 or 2..65535')
        if not isinstance(row.get('name'), str) or not row['name'] or len(row['name']) > 128:
            raise OverlayError('Packet name is required')
        if 'note' in row and (not isinstance(row['note'], str) or len(row['note']) > 1024):
            raise OverlayError('packet note must be a short string')
        fields = row.get('fields', {})
        if not isinstance(fields, dict) or len(fields) > 256:
            raise OverlayError('fields must be a bounded object')
        for name, spec in fields.items():
            _validate_field(name, spec)
        if 'min_length' in row:
            _integer(row['min_length'], 'min_length', 2, 65535)
        if 'template' in row and (not isinstance(row['template'], str) or len(row['template']) > 16384):
            raise OverlayError('template must be a string')
    return document


def overlay_lengths(overlay):
    result = {}
    for row in overlay['packets']:
        result[_parse_id(row['id'], 'id')] = row['length']
    return result


def merge_lengths(base, overlay):
    """Return a new length map; overlay IDs win explicitly."""
    if not isinstance(base, dict) or not base:
        raise OverlayError('Base PacketLength map is required')
    merged = dict(base)
    merged.update(overlay_lengths(overlay))
    return merged


def overlay_display_rules(overlay):
    """Convert overlay packets into display-profile packet rules."""
    rules = []
    for row in overlay['packets']:
        pid = _parse_id(row['id'], 'id')
        fields = {}
        for name, spec in row.get('fields', {}).items():
            fields[name] = {key: value for key, value in spec.items()}
        rule = dict(
            ids=[f'{pid:04X}'],
            name=row['name'],
            fields=fields,
            template=row.get('template', '@overlay_packet 0x' + f'{pid:04X};'),
            min_length=row.get('min_length', 2 if row['length'] == -1 else min(row['length'], 65535)),
        )
        rules.append(rule)
    return rules


def merge_display_document(document, overlay):
    """Deep-copy a display JSON document and replace/add rules for overlay IDs."""
    result = deepcopy(document)
    packets = list(result.get('packets') or [])
    overlay_rules = overlay_display_rules(overlay)
    overlay_ids = {int(rule['ids'][0], 16) for rule in overlay_rules}
    kept = []
    for rule in packets:
        ids = []
        for pid in rule.get('ids', []):
            number = int(pid, 16)
            if number not in overlay_ids:
                ids.append(pid)
        if not ids:
            continue
        if len(ids) != len(rule['ids']):
            rule = deepcopy(rule)
            rule['ids'] = ids
        kept.append(rule)
    # Validate overlay rules through DisplayProfile field rules by constructing via Profile later.
    result['packets'] = kept + overlay_rules
    return result


def resolve_index_label(tag, value, *, world=None, capture_session=0, connection=None, flow_id=None,
                        client_names=None, reference_names=None, skill_names=None):
    """Return annotation text, never substituting missing evidence."""
    if tag not in INDEX_TAGS:
        return '未登録'
    if tag == 'actor_id':
        if type(value) is not int or not 0 <= value <= 0xffffffff:
            return '未登録'
        if world is None or connection is None:
            return '未観測'
        scope = (capture_session, connection)
        scene = world.scenes.get(scope)
        entity = None
        if scene is not None:
            key = world.current.get((*scope, scene.generation, value))
            entity = world.entities.get(key)
        if entity is None:
            for row in world.records(active_only=False):
                if (row.capture_session == capture_session and row.actor_id == value
                        and row.connection == connection):
                    entity = row
                    break
        if entity is None:
            return '未観測'
        name = entity.name if isinstance(entity.name, str) and entity.name else ''
        return name if name else '未観測'
    if tag == 'item_id':
        if type(value) is not int or value <= 0:
            return '未登録'
        if client_names is None:
            return '未登録'
        label = item_name(client_names, value)
        return label
    if tag == 'quest_id':
        if type(value) is not int or value < 0:
            return '未登録'
        if client_names is None:
            return '未登録'
        label = quest_label(client_names, value)
        return label if label else '未登録'
    if tag == 'map_name':
        if not isinstance(value, str) or not value:
            return '未登録'
        if client_names is None:
            return '未登録'
        label = map_label(client_names, value)
        return label if label else '未登録'
    if tag == 'class_id':
        if type(value) is not int or not 0 <= value <= 65535:
            return '未登録'
        from reconstruction.actor_appearance import player_class
        # player_classes.json is an ID set only; do not invent NPC class names.
        return '職業クラス' if player_class(value) else '未登録'
    if tag == 'skill_id':
        if type(value) is not int or value <= 0:
            return '未登録'
        catalog = skill_names
        if catalog is None:
            try:
                catalog = load_skill_names()
            except (OSError, ValueError):
                return '未登録'
        if isinstance(catalog, dict):
            label = catalog.get(value)
            if isinstance(label, str) and label.strip():
                return label
        return '未登録'
    if tag in ('status_icon', 'visual_effect'):
        if type(value) is not int or value < 0:
            return '未登録'
        if reference_names is None:
            return '未登録'
        labels = reference_labels(reference_names, tag, value)
        symbol = labels.get('reference_symbols') or ''
        if labels.get('reference_known') and symbol:
            return symbol
        return '未登録'
    return '未登録'


def format_indexed_value(value, label):
    if label is None or label == '':
        return value
    return f'{value}（{label}）'


def load_display_document(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise OverlayError('Display profile exceeds 2 MiB')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverlayError(f'Invalid display JSON: {exc}') from exc


def load_profile_with_overlay(path, overlay=None):
    """Load a DisplayProfile, optionally replacing/adding overlay packet rules."""
    from parser.display import DisplayProfile
    document = load_display_document(path)
    if overlay is not None:
        document = merge_display_document(document, overlay)
    return DisplayProfile(document)


def overlay_evidence(overlay):
    """Public evidence fields for SessionLog (no private keys)."""
    if overlay is None:
        return None
    return dict(
        sha256=overlay.get('_sha256'),
        path=overlay.get('_path'),
        packet_count=len(overlay.get('packets') or ()),
    )


def write_overlay_snapshot(directory, overlay):
    """Persist the applied overlay beside PacketLength.used.txt."""
    payload = {key: value for key, value in overlay.items() if not str(key).startswith('_')}
    path = Path(directory) / 'PacketOverlay.used.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path
