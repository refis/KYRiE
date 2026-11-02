"""Parse client MapTypeProperty.txt into type catalogs and comment-only mapflag candidates.

MapTypeProperty is keyed by MAPTYPE number (0..N), not by map name. Per-map mapflag
lines require an observed or otherwise evidenced (map_name, type) pair. Unset
ADD_PROPERTY defaults to FALSE per the file notes. Candidates are review comments,
not executable server truth.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_TYPES = 64
CATALOG_VERSION = 1

# Conservative client ADD_PROPERTY → emulator mapflag *comment* suggestions.
# Only high/medium alignments; low-confidence or ambiguous properties stay as notes.
PROPERTY_MAPFLAG_HINTS = {
    ('TELEPORT', False): (
        dict(flag='noteleport', confidence='medium',
             note='Client blocks teleport items/skills for the type; server noteleport is broader'),
    ),
    ('NOTREMEMBER', False): (
        dict(flag='nomemo', confidence='medium',
             note='Client blocks /memo and related remember behavior'),
    ),
    ('DISCONNECT_NOTREMEMBER', True): (
        dict(flag='nosave', args='SavePoint', confidence='medium',
             note='Logout returns to save point; confirm SavePoint vs fixed map'),
    ),
    ('CALLMONSTER', False): (
        dict(flag='nobranch', confidence='medium',
             note='Dead Branch family blocked on client for the type'),
    ),
    ('PK', True): (
        dict(flag='pvp', confidence='medium',
             note='PK allowed; pvp_noparty/pvp_noguild need separate evidence'),
    ),
    ('SIEGE', True): (
        dict(flag='gvg', confidence='low',
             note='Siege-like client mode; gvg_castle/gvg_te/agit DB may apply — review only'),
    ),
    ('DENYSKILL', True): (
        dict(flag='noskill', confidence='medium',
             note='Client denies active skills'),
    ),
    ('DENY_BUTTERFLY', True): (
        dict(flag='noreturn', confidence='low',
             note='Butterfly Wing family; noreturn is only a partial analogue'),
    ),
    ('DISABLE_LOCKON', True): (
        dict(flag='nolockon', confidence='medium',
             note='Shift-free lock-on disabled'),
    ),
    ('USE_SIMPLE_EFFECT', True): (
        dict(flag='forcemineffect', confidence='medium',
             note='Simplified skill effects'),
    ),
    ('BATTLEFIELD', True): (
        dict(flag='battleground', confidence='medium',
             note='Battleground client mode; scoreboard arg not inferred'),
    ),
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_maptype_property(path) -> tuple[bytes, str]:
    path = Path(path)
    data = path.read_bytes()
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError('MapTypeProperty source size is out of supported bounds')
    return data, _digest(data)


def _strip_line_comment(line: str) -> str:
    return line.split('//', 1)[0].strip()


def parse_maptype_property(text: str) -> dict:
    """Return {types: {id: {...}}, parse_issues: [...]} from UTF-8/CP932-decoded text."""
    if not isinstance(text, str) or not text:
        raise ValueError('MapTypeProperty text is required')
    # Drop block comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    types = {}
    issues = []
    current = None
    label = None
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = _strip_line_comment(raw)
        if not line:
            continue
        header = re.match(r'^MAPTYPE\s+(\d+)\s*(?:\/\/\s*(.*))?$', raw.strip())
        if header:
            number = int(header.group(1))
            if not 0 <= number < MAX_TYPES:
                issues.append(dict(line=line_no, reason='maptype_out_of_range', value=number))
                current = None
                continue
            if number in types:
                issues.append(dict(line=line_no, reason='duplicate_maptype', value=number))
            label = (header.group(2) or '').strip() or None
            types[number] = dict(
                id=number, label=label, properties={}, property_values={},
                block_skills=[], block_items=[], block_equip=[], block_buffs=[],
                adjustments=[],
            )
            current = types[number]
            continue
        if line == '{':
            if current is None:
                issues.append(dict(line=line_no, reason='orphan_brace'))
            continue
        if line == '}':
            current = None
            continue
        if current is None:
            # Preamble / changelog outside blocks is ignored when inactive after comment strip
            continue
        if m := re.fullmatch(r'ADD_PROPERTY\s*\(\s*([A-Z0-9_]+)\s*,\s*(TRUE|FALSE)\s*\)\s*;?', line):
            current['properties'][m.group(1)] = m.group(2) == 'TRUE'
            continue
        if m := re.fullmatch(r'ADD_PROPERTY_VALUE\s*\(\s*([A-Z0-9_]+)\s*,\s*([^)]+?)\s*\)\s*;?', line):
            current['property_values'][m.group(1)] = m.group(2).strip()
            continue
        if m := re.fullmatch(r'ADD_BLOCK_SKILL\s*\(\s*([^)]+?)\s*\)\s*;?', line):
            current['block_skills'].append(m.group(1).strip())
            continue
        if m := re.fullmatch(r'ADD_BLOCK_ITEM\s*\(\s*"([^"]+)"\s*\)\s*;?', line):
            current['block_items'].append(m.group(1))
            continue
        if m := re.fullmatch(r'ADD_BLOCK_EQUIPITEM\s*\(\s*"([^"]+)"\s*\)\s*;?', line):
            current['block_equip'].append(m.group(1))
            continue
        if m := re.fullmatch(r'ADD_BLOCK_BUFF\s*\(\s*"([^"]+)"\s*\)\s*;?', line):
            current['block_buffs'].append(m.group(1))
            continue
        if m := re.fullmatch(r'ADJUST_(?:TRAP_DURATION|SKILL_DAMAGE)\s*\(\s*([^)]+?)\s*\)\s*;?', line):
            current['adjustments'].append(line.rstrip(';'))
            continue
        issues.append(dict(line=line_no, reason='unsupported_statement', sample=line[:80]))
    if len(types) > MAX_TYPES:
        raise ValueError('MapTypeProperty type capacity exceeded')
    return dict(types={str(k): types[k] for k in sorted(types)}, parse_issues=issues)


def mapflag_candidates_for_type(entry: dict) -> list:
    """Build review-only mapflag candidate rows for one MAPTYPE entry.

    Unset booleans default to FALSE (file note). Only (property, value) pairs with a
    registered hint become candidates.
    """
    explicit = dict(entry.get('properties') or {})
    considered = dict(explicit)
    for name, _value in PROPERTY_MAPFLAG_HINTS:
        considered.setdefault(name, False)
    rows = []
    seen = set()
    for name, value in sorted(considered.items()):
        hints = PROPERTY_MAPFLAG_HINTS.get((name, value), ())
        for hint in hints:
            key = (hint['flag'], hint.get('args'))
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(
                property=name, property_value=value, flag=hint['flag'],
                args=hint.get('args'), confidence=hint['confidence'], note=hint['note'],
                property_explicit=name in explicit,
            ))
    return rows


def format_mapflag_comments(map_name: str, type_id: int, entry: dict, *, source_sha256: str) -> list[str]:
    """Emit comment lines only; never claim executable server mapflags."""
    if not isinstance(map_name, str) or not map_name or '/' in map_name or '\\' in map_name:
        raise ValueError('Map name is invalid')
    base = map_name[:-4] if map_name.endswith('.gat') else map_name
    if not re.fullmatch(r'[0-9A-Za-z_@.-]+', base):
        raise ValueError('Map name contains unsupported characters')
    label = entry.get('label') or 'unlabeled'
    lines = [
        f'// mapflag candidates from MapTypeProperty MAPTYPE {type_id} ({label}); '
        f'source_sha256={source_sha256[:16]}…; review only — not server truth',
    ]
    for row in mapflag_candidates_for_type(entry):
        args = f"\t{row['args']}" if row.get('args') else ''
        origin = 'explicit' if row.get('property_explicit') else 'default_FALSE'
        lines.append(
            f"// {base}\tmapflag\t{row['flag']}{args}"
            f"  // {row['property']}={'TRUE' if row['property_value'] else 'FALSE'}"
            f" ({origin}) confidence={row['confidence']}"
        )
    if len(lines) == 1:
        lines.append(f'// (no conservative mapflag hints for MAPTYPE {type_id})')
    block_items = entry.get('block_items') or []
    block_skills = entry.get('block_skills') or []
    if block_items or block_skills:
        lines.append(
            f'// additional client blocks: items={len(block_items)} skills={len(block_skills)} '
            f'(no automatic restricted-zone / item_noequip invent)'
        )
    return lines


def suggest_mapflag_comments(catalog: dict, map_name: str, type_id: int) -> dict:
    """Look up catalog type and return comment candidates or an unresolved reason."""
    if type(type_id) is not int or type_id < 0:
        raise ValueError('type_id must be a non-negative int')
    key = str(type_id)
    types = catalog.get('types') or {}
    source = (catalog.get('sources') or [{}])[0]
    sha = source.get('sha256') or catalog.get('source_sha256') or 'unknown'
    if key not in types:
        return dict(
            ok=False, map_name=map_name, type_id=type_id,
            reason='type_not_in_maptype_property_catalog',
            comments=[
                f'// mapflag candidates unavailable: MAPTYPE {type_id} not in MapTypeProperty catalog '
                f'(observed wire kind may be extended / unrelated to this file)',
            ],
        )
    entry = types[key]
    return dict(
        ok=True, map_name=map_name, type_id=type_id, label=entry.get('label'),
        comments=format_mapflag_comments(map_name, type_id, entry, source_sha256=sha),
        candidates=mapflag_candidates_for_type(entry),
    )


def build_catalog(path) -> dict:
    data, digest = read_maptype_property(path)
    # Prefer UTF-8; fall back to cp932 for localized copies
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('cp932')
    parsed = parse_maptype_property(text)
    types = {}
    for key, entry in parsed['types'].items():
        row = dict(entry)
        row['mapflag_candidates'] = mapflag_candidates_for_type(entry)
        types[key] = row
    return dict(
        version=CATALOG_VERSION,
        kind='maptype_property_catalog',
        sources=[dict(path=str(Path(path).resolve()), sha256=digest)],
        type_count=len(types),
        types=types,
        parse_issues=parsed['parse_issues'],
        map_name_binding='not_in_file',
        generation_policy='comment_only_with_observed_map_and_type',
        property_default='FALSE when unset',
        executable_mapflags=False,
        notes=[
            'MapTypeProperty has no per-map rows; rotool-style map pages or 01D6/099B observations supply map→type',
            '099B flags bitfield is not decoded here',
            'Wire kinds outside catalog range must not invent MAPTYPE rows',
        ],
    )
