"""Read-only percentage evidence preceding a skill notification; no threshold inference."""
from bisect import bisect_left
from copy import deepcopy
import math


def scope(row):
    return (tuple(row['entity_key']),row['class_id'])


def finite(value):
    try:
        return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:
        return False


def skill_hp_contexts(skills,performance,changes=(),history_complete=True):
    buckets = {}
    for row in performance:
        if row.get('packet_id') == 0xa36 and row.get('role') == 'state' and 'hp_percent' in row:
            buckets.setdefault(scope(row),[]).append(row)
    indices = {}
    for key,rows in buckets.items():
        rows.sort(key=lambda row:row['packet_index'])
        indices[key] = [row['packet_index'] for row in rows]
    barriers = {}
    for change in changes:
        if change.get('kind')=='MOB' and 'class_id' in change.get('changes',{}):
            key=(change['capture_session'],change['connection'],change['map_generation'],change['actor_id'])
            barriers.setdefault(key,[]).append(change['packet_index'])
    for values in barriers.values():values.sort()
    result = []
    for skill in skills:
        context = dict(status='not_observed',hp_percent=None,packet_index=None,age_ms=None,
                       resolution_percent=5,flags=[],condition_confirmed=False)
        key = scope(skill)
        position = bisect_left(indices.get(key,[]),skill['packet_index'])-1
        if position >= 0:
            row = buckets[key][position]
            context.update(hp_percent=row['hp_percent'],packet_index=row['packet_index'],
                           timestamp=row['timestamp'],flags=sorted(set(row['flags'])|set(skill['flags'])))
            if not finite(skill['timestamp']) or not finite(row['timestamp']) or skill['timestamp'] < row['timestamp']:
                context['status'] = 'invalid_time'
            else:
                age = (skill['timestamp']-row['timestamp'])*1000
                if not finite(age):
                    context['status'] = 'invalid_time'
                else:
                    context['age_ms'] = round(age,3)
                    key=tuple(skill['entity_key'])
                    stops=barriers.get(key[:4],[])
                    end=bisect_left(stops,skill['packet_index'])
                    changed=end>0 and stops[end-1]>row['packet_index']
                    if not history_complete:context['flags'].append('appearance_history_incomplete')
                    context['status'] = ('class_changed' if changed else 'invalid_percent'
                        if type(row['hp_percent']) is not int or not 0<=row['hp_percent']<=100
                        else 'quality_warning' if context['flags'] else 'observed')
                    if changed:context['class_change_packet_index']=stops[end-1]
        result.append(context)
    return deepcopy(result)


def compare_percentage(context,threshold,relation):
    if relation not in ('none','le','ge') or type(threshold) is not int or not 0<=threshold<=100:
        raise ValueError('Invalid percentage comparison')
    if relation == 'none':
        return None
    if context['status'] != 'observed':
        return None
    value = context['hp_percent']
    return value<=threshold if relation=='le' else value>=threshold
