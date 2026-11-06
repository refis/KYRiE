"""Workspace NPC roster for cross-log review hints (never script identity)."""
from copy import deepcopy


def build_npc_roster(world, source_refs=None, *, max_entries=4096):
    """Collect named NPCs across capture sessions for review labeling only.

    Prefer placement-complete rows (`identified_placement`). Named rows without
    full placement remain as `named_entity`. ActorIDs are never merged across
    sessions; callers must treat matches as candidates.
    """
    if world is None:
        return []
    source_refs = source_refs or {}
    entries = []
    for entity in world.records('NPC', active_only=False):
        if not isinstance(entity.name, str) or not entity.name:
            continue
        placement = (isinstance(entity.map_name, str) and entity.map_name
                     and all(getattr(entity, name) is not None
                             for name in ('class_id', 'x', 'y', 'direction')))
        entry = dict(
            name=entity.name,
            map_name=entity.map_name if isinstance(entity.map_name, str) else None,
            class_id=entity.class_id,
            x=entity.x,
            y=entity.y,
            direction=entity.direction,
            actor_id=entity.actor_id,
            capture_session=entity.capture_session,
            source_ref=source_refs.get(entity.capture_session, ''),
            scope='identified_placement' if placement else 'named_entity')
        entries.append(entry)
        if len(entries) >= max_entries:
            break
    return entries


def roster_candidates(roster, *, actor_id, capture_session=None, limit=5):
    """Other-session named NPCs sharing actor_id. Review hints only."""
    if type(actor_id) is not int or not roster:
        return []
    matches = []
    seen = set()
    for entry in roster:
        if entry.get('actor_id') != actor_id:
            continue
        if capture_session is not None and entry.get('capture_session') == capture_session:
            continue
        if not isinstance(entry.get('name'), str) or not entry['name']:
            continue
        key = (entry['name'], entry.get('map_name'), entry.get('capture_session'),
               entry.get('source_ref'))
        if key in seen:
            continue
        seen.add(key)
        row = deepcopy(entry)
        row['match'] = 'actor_id'
        matches.append(row)
        if len(matches) >= limit:
            break
    return matches


def format_roster_candidates(candidates):
    """Short Japanese note for presentation / trial UI."""
    if not candidates:
        return ''
    parts = []
    for row in candidates[:5]:
        where = row.get('map_name') or 'MAP不明'
        source = row.get('source_ref') or f"ses{row.get('capture_session')}"
        # Keep path tails readable without inventing identity.
        label = source.replace('\\', '/').rsplit('/', 1)[-1] if source else '出典不明'
        parts.append(f'{row["name"]}（{where} / {label}）')
    return ('他ログ候補: ' + '、'.join(parts)
            + '。ActorID一致の表示ヒントであり、同一視・スクリプト反映はしません。')
