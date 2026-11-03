"""Associate dialogue setquest/delquest with later showevent into OnQuestInfo."""
from copy import deepcopy
import json

from reconstruction.instance_names import npc_name as base_npc_name

MAX_QUEST_INFO_LINKS = 256


def associate_quest_showevent(conversation, marker):
    """Link an event_marker to the latest unmatched setquest/delquest in the same conversation.

    Returns the link dict when associated, otherwise None. Does not invent NPC names:
    uses the marker target NPC name, else the conversation NPC when the actor matches.
    """
    if conversation is None or marker is None or marker.get('kind') != 'event_marker':
        return None
    if len(conversation.quest_info_links) >= MAX_QUEST_INFO_LINKS:
        return None
    marker_index = marker.get('packet_index')
    if type(marker_index) is not int:
        return None
    if any(row['marker_packet_index'] == marker_index for row in conversation.quest_info_links):
        return None
    used = {row['quest_packet_index'] for row in conversation.quest_info_links}
    candidates = [row for row in conversation.resource_observations
                  if row['kind'] in ('quest_add', 'quest_delete')
                  and type(row.get('packet_index')) is int
                  and row['packet_index'] < marker_index
                  and row['packet_index'] not in used
                  and type(row.get('fields', {}).get('quest_id')) is int]
    if not candidates:
        return None
    quest = candidates[-1]
    fields = marker.get('fields') or {}
    if not all(type(fields.get(name)) is int for name in ('state', 'kind', 'x', 'y')):
        return None
    if not all(0 <= fields[name] <= 65535 for name in ('state', 'kind', 'x', 'y')):
        return None
    target_name = None
    npc = marker.get('npc') or {}
    if isinstance(npc.get('name'), str) and npc['name']:
        target_name = npc['name']
    elif marker.get('actor_id') == conversation.actor_id and isinstance(conversation.npc.get('name'), str):
        target_name = conversation.npc['name'] or None
    if not target_name:
        return None
    link = dict(
        quest_id=quest['fields']['quest_id'],
        quest_kind=quest['kind'],
        quest_packet_index=quest['packet_index'],
        quest_timestamp=quest.get('timestamp'),
        state=fields['state'],
        kind=fields['kind'],
        x=fields['x'],
        y=fields['y'],
        target_name=target_name,
        target_map_name=npc.get('map_name') or conversation.npc.get('map_name'),
        target_actor_id=marker.get('actor_id'),
        marker_packet_index=marker_index,
        marker_timestamp=marker.get('timestamp'),
        after_close_reply=bool(quest.get('after_close_reply') or marker.get('after_close_reply')),
        cause_confirmed=False,
    )
    conversation.quest_info_links.append(link)
    marker['quest_info_linked'] = True
    marker['quest_info_quest_id'] = link['quest_id']
    if 'fields' in marker and isinstance(marker['fields'], dict):
        marker['fields'] = dict(marker['fields'], quest_info_linked=True, quest_id=link['quest_id'])
    quest['showevent_linked'] = True
    quest['showevent_marker_packet_index'] = marker_index
    return link


def collect_quest_info_links(*conversations):
    """Chronological unique OnQuestInfo candidates across conversations."""
    rows = []
    seen = set()
    for conversation in conversations:
        if conversation is None:
            continue
        links = getattr(conversation, 'quest_info_links', None)
        if links is None and isinstance(conversation, dict):
            links = conversation.get('quest_info_links')
        for link in links or ():
            key = (link.get('quest_id'), link.get('state'), link.get('kind'),
                   link.get('x'), link.get('y'), link.get('target_name'),
                   link.get('marker_packet_index'), link.get('quest_packet_index'))
            if key in seen:
                continue
            seen.add(key)
            rows.append(deepcopy(link))
    rows.sort(key=lambda row: (
        row.get('quest_timestamp') is None, row.get('quest_timestamp') or 0,
        row.get('marker_timestamp') is None, row.get('marker_timestamp') or 0,
        row.get('quest_packet_index') or 0, row.get('marker_packet_index') or 0))
    return rows


def _conversation_resources(conversation):
    if conversation is None:
        return (), ()
    if isinstance(conversation, dict):
        return (conversation.get('resource_observations') or (),
                conversation.get('quest_info_links') or ())
    return (getattr(conversation, 'resource_observations', None) or (),
            getattr(conversation, 'quest_info_links', None) or ())


def quest_flow_rows(*conversations):
    """Chronological setquest/delquest rows with optional linked showevent fields.

    Includes unassociated quest add/delete so the Quest tab can show the full
    observed quest flow, not only OnQuestInfo-ready pairs.
    """
    rows = []
    seen = set()
    for conversation in conversations:
        resources, links = _conversation_resources(conversation)
        by_quest = {link.get('quest_packet_index'): link for link in links
                    if type(link.get('quest_packet_index')) is int}
        for resource in resources:
            if resource.get('kind') not in ('quest_add', 'quest_delete'):
                continue
            packet_index = resource.get('packet_index')
            quest_id = resource.get('fields', {}).get('quest_id')
            if type(packet_index) is not int or type(quest_id) is not int:
                continue
            key = (packet_index, quest_id, resource['kind'])
            if key in seen:
                continue
            seen.add(key)
            link = by_quest.get(packet_index)
            row = dict(
                quest_kind=resource['kind'],
                quest_id=quest_id,
                quest_packet_index=packet_index,
                quest_timestamp=resource.get('timestamp'),
                after_close_reply=bool(resource.get('after_close_reply')
                                       or (link or {}).get('after_close_reply')),
                linked=link is not None,
            )
            if link is not None:
                row.update(
                    state=link.get('state'), kind=link.get('kind'),
                    x=link.get('x'), y=link.get('y'),
                    target_name=link.get('target_name'),
                    marker_packet_index=link.get('marker_packet_index'),
                    marker_timestamp=link.get('marker_timestamp'),
                )
            rows.append(row)
    rows.sort(key=lambda row: (
        row.get('quest_timestamp') is None, row.get('quest_timestamp') or 0,
        row.get('quest_packet_index') or 0,
        row.get('marker_timestamp') is None, row.get('marker_timestamp') or 0,
        row.get('marker_packet_index') or 0))
    return rows


def render_quest_info(links, templates, *, map_name=None):
    """Render an OnQuestInfo label with associated showevent lines."""
    links = list(links or ())
    if not links:
        return ''
    label = templates.get('onquestinfo')
    command = templates.get('showevent_quest')
    end = templates.get('end')
    indent = templates.get('indent', '    ')
    if label != 'OnQuestInfo:' or not isinstance(command, str) or not isinstance(end, str):
        raise ValueError('OnQuestInfo templates are invalid')
    if end.strip() != 'end;':
        raise ValueError('OnQuestInfo end template is invalid')
    lines = [label]
    for link in links:
        name = base_npc_name(link['target_name'], link.get('target_map_name') or map_name)
        quoted = json.dumps(name, ensure_ascii=False)
        target_map = link.get('target_map_name') or map_name or ''
        if '@' in target_map and 'instance_npc_reference' in templates:
            quoted = templates['instance_npc_reference'].format(name=quoted)
        lines.append(indent + command.format(
            state=link['state'], kind=link['kind'], name=quoted,
            quest_id=link['quest_id'], x=link['x'], y=link['y']))
    lines.append(indent + end)
    result = '\n'.join(lines) + '\n'
    if len(result) > 4 * 1024 * 1024:
        raise ValueError('OnQuestInfo output exceeds size limit')
    return result


def append_quest_info(body, links, templates, *, map_name=None):
    block = render_quest_info(links, templates, map_name=map_name)
    if not block:
        return body
    result = body.rstrip() + '\n\n' + block
    if len(result) > 4 * 1024 * 1024:
        raise ValueError('NPC body and OnQuestInfo exceed output size limit')
    return result
