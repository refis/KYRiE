"""Projection-only instance names. Never trim a partial NPC suffix."""
import re


def instance_parts(name):
    if not isinstance(name, str):
        return None
    match = re.fullmatch(r'([A-Za-z0-9]{3})([0-9]+@[^\s]+)', name)
    return match.groups() if match else None


def map_name(name):
    parts = instance_parts(name)
    return parts[1] if parts else name


def npc_name(name, raw_map):
    parts = instance_parts(raw_map)
    if parts and isinstance(name, str) and name.endswith('_' + parts[0]):
        return name[:-4]
    return name


def projection(npc):
    raw_map, raw_name = npc.get('map_name'), npc.get('name')
    projected = npc_name(raw_name, raw_map)
    parts = instance_parts(raw_map)
    partial = bool(parts and isinstance(raw_name, str) and any(
        raw_name.endswith('_' + parts[0][:length]) for length in range(3)))
    return dict(raw_map_name=raw_map, raw_npc_name=raw_name,
                map_name=map_name(raw_map), npc_name=projected,
                npc_suffix_status='complete_removed' if projected != raw_name else 'ambiguous_partial' if partial else 'unchanged')
