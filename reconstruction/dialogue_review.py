"""Locate excluded observations without completing or reclassifying them."""


def build_review_queue(conversations, merged):
    lookup = {(row['capture_session'], row['id']): row for row in conversations}
    result = []
    for excluded in merged.get('excluded', []):
        item = lookup.get((excluded['capture_session'], excluded['conversation_id']))
        if item is None:
            continue
        steps = item.get('steps', [])
        npc = item.get('npc', {})
        result.append(dict(source_ref=excluded['source_ref'], capture_session=item['capture_session'],
            conversation_id=item['id'], actor_id=item['actor_id'], npc_name=npc.get('name') or '',
            map_name=npc.get('map_name') or '', status=item['status'], observed_open=item['observed_open'],
            reason=excluded['reason'], quality_flags=list(excluded.get('quality_flags', [])),
            first_packet_index=steps[0]['packet_index'] if steps else None,
            last_packet_index=steps[-1]['packet_index'] if steps else None))
    return result
