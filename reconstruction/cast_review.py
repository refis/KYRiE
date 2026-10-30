"""Read-only view of existing cast associations; never create new links."""
import math
from copy import deepcopy


def build_cast_review(observations):
    def scope(row):
        return (tuple(row['entity_key']), row['class_id'], row['skill_id'], row['capture_session'])
    casts = {(row['packet_index'], scope(row)): row for row in observations if row['kind'] == 'cast'}
    endings = {}
    for row in observations:
        if row['kind'] not in ('cancel', 'effect', 'damage', 'ground'):
            continue
        key = (row.get('linked_cast_index'), scope(row))
        if key in casts:
            endings.setdefault(key, []).append(row)
    result = []
    for key, cast in casts.items():
        for ending in endings.get(key, [None]):
            elapsed = None
            if ending is not None:
                difference = (ending['timestamp'] - cast['timestamp']) * 1000
                if math.isfinite(difference) and difference >= 0:
                    elapsed = round(difference, 3)
            result.append(dict(entity_key=list(cast['entity_key']), class_id=cast['class_id'],
                skill_id=cast['skill_id'], capture_session=cast['capture_session'],
                target_id=cast.get('target_id'), notified_cast_ms=cast['cast_ms'],
                outcome=cast.get('cast_outcome', 'pending'),
                end_kind=ending['kind'] if ending else None, elapsed_ms=elapsed,
                from_packet_index=cast['packet_index'], packet_index=ending['packet_index'] if ending else None,
                flags=sorted(set(cast['flags']) | set(ending['flags'] if ending else [])),
                tracking_end=deepcopy(cast.get('tracking_end')),
                association_confirmed=False))
    return result
