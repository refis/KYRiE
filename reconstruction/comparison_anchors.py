"""Observed comparison anchors; no generated triggers or timer values."""
from copy import deepcopy
from bisect import bisect_right
import hashlib
import json
from reconstruction.conversation_actions import validate_actions
from reconstruction.actor_appearance import declaration_class
from reconstruction.instance_names import map_name, npc_name, projection

ANCHOR_KINDS = ('dialogue_start', 'map_arrival')
MAX_COMPARISON_ROWS = 14000


def _action_context(item,action):
    prompt_pair=next(((index,item.steps[index]) for index in range(action['after_step_index'],-1,-1)
                      if item.steps[index]['kind'] in ('next','menu','number','text','close')),None)
    if prompt_pair is not None:
        prompt_index,prompt=prompt_pair
        reply=prompt.get('reply')
        expected={'next':'continue','menu':'choice','number':'number_reply','text':'text_reply','close':'dismiss'}[prompt['kind']]
        answered=(type(reply) is int and 0<=reply<len(item.steps)
                  and item.steps[reply]['kind']==expected and item.steps[reply].get('reply_to')==prompt_index
                  and item.steps[reply]['direction']=='SEND'
                  and prompt['packet_index']<item.steps[reply]['packet_index']<action['packet_index'])
        if not answered:return 'close_wait' if prompt['kind']=='close' else 'input_wait'
    if action.get('after_close_reply'):return 'after_close_reply'
    if action['kind']=='npc_display_action' and action['fields']['outside']:return 'outside_visibility'
    target=action['fields'].get('target')
    if isinstance(target,dict):
        if not target.get('name') or not target.get('map_name'):return 'target_unresolved'
        # Compare raw instance maps before projecting away runtime tokens.
        if target['map_name']!=item.npc.get('map_name'):return 'target_different_map'
        if projection(target)['npc_suffix_status']=='ambiguous_partial':return 'target_name_ambiguous'
    if action['kind']=='script_command' and action['fields']['command']=='dropitem':
        destination=action['fields']['arguments'].get('map_name')
        if not destination:return 'target_unresolved'
        if destination!=item.npc.get('map_name'):return 'target_different_map'
    if action['fields'].get('review_only'):return 'review_only'
    return 'during_dialogue'


def _action_observations(item,seen_packets,seen_actions):
    try:validate_actions(item)
    except (KeyError,TypeError,OverflowError) as exc:
        raise ValueError('会話アクションの根拠を検証できません。') from exc
    for action in item.actions:
        packet=(item.capture_session,action['packet_index'])
        if packet in seen_packets:continue
        raw=deepcopy(action['fields'])
        digest=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=True,allow_nan=False).encode('ascii')).digest()
        key=(item.capture_session,item.flow_id,item.actor_id,action['packet_index'],action['kind'],action['after_step_index'],digest)
        if key in seen_actions:continue
        seen_actions.add(key)
        fields=deepcopy(raw)
        if action['kind']=='status_action':fields.pop('tick',None)
        target=fields.get('target')
        if isinstance(target,dict):
            target['name']=npc_name(target.get('name'),target.get('map_name'))
            target['map_name']=map_name(target.get('map_name'))
            effect_target=dict(role='npc',**deepcopy(target))
        elif action['kind']=='script_command' and fields['command']=='dropitem':
            fields['arguments']['map_name']=map_name(fields['arguments']['map_name'])
            effect_target=dict(role='map',map_name=fields['arguments']['map_name'])
        elif action['kind']=='visibility_action':
            effect_target=dict(role='dialogue_npc',name=npc_name(item.npc.get('name'),item.npc.get('map_name')))
        else:
            effect_target=dict(role='player' if action['kind']=='status_action' else 'unassigned')
        # actor_id/npc describe the dialogue scope, never the effect recipient.
        yield dict(kind=action['kind'],fields=fields,raw_fields=raw,
            capture_session=item.capture_session,flow_id=item.flow_id,actor_id=item.actor_id,
            entity_kind='NPC',target_observed=True,context=_action_context(item,action),
            timestamp=action['timestamp'],packet_index=action['packet_index'],packet_id=action['packet_id'],
            direction=action['direction'],connection=action['connection'],source=action['source'],
            npc={name:deepcopy(item.npc.get(name)) for name in
                 ('map_name','name','class_id','x','y','direction','appearance','map_generation')},
            comparison_scope='dialogue_owner',effect_target=effect_target,
            association_basis='recorded_dialogue_action',cause_confirmed=False,
            after_step_index=action['after_step_index'])


def comparison_rows(store, mode='presentation',*,include_actions=False):
    if type(include_actions) is not bool:raise ValueError('Invalid action comparison option')
    rows = deepcopy(store.presentation_observations)
    if mode == 'presentation':
        return rows
    if mode not in ANCHOR_KINDS:
        raise ValueError('Unknown comparison anchor mode')
    starts = []
    for item in store.sessions:
        if not item.steps or not item.npc or not (item.observed_open or item.npc.get('touch')):
            continue
        step = item.steps[0]
        starts.append(dict(kind='dialogue_start', fields=dict(start_kind=step['kind']),
            capture_session=item.capture_session, flow_id=item.flow_id, actor_id=item.actor_id,
            entity_kind='NPC', target_observed=True, context='comparison_anchor',
            anchor_type='dialogue_start', timestamp=step['timestamp'], packet_index=step['packet_index'],
            packet_id=step['packet_id'], direction=step['direction'], connection=step['connection'],
            source=step['source'], npc={key: deepcopy(item.npc.get(key)) for key in
                ('map_name','name','class_id','x','y','direction','appearance','map_generation')}))
        starts[-1]['npc']['initial_display'] = {'class_id': declaration_class(item.npc)}
    if mode == 'dialogue_start':
        observed = {(row['capture_session'], row['packet_index']) for row in rows}
        kinds = {'emotion','effect','effect_value','effect_remove','sound','cutin','classchange',
                 'progressbar','viewpoint','overhead','announcement','unittalk'}
        for item in store.sessions:
            for step in item.steps:
                key = (item.capture_session, step['packet_index'])
                if step['kind'] not in kinds or key in observed:
                    continue
                if len(rows) >= MAX_COMPARISON_ROWS - len(starts):
                    raise ValueError('比較観測が保持上限を超えています。')
                observed.add(key)
                rows.append(dict(kind=step['kind'], fields=deepcopy(step['fields']),
                    capture_session=item.capture_session, flow_id=item.flow_id, actor_id=item.actor_id,
                    entity_kind='NPC', target_observed=True, context='during_dialogue',
                    timestamp=step['timestamp'], packet_index=step['packet_index'], packet_id=step['packet_id'],
                    direction=step['direction'], connection=step['connection'], source=step['source'],
                    npc={name:deepcopy(item.npc.get(name)) for name in
                         ('map_name','name','class_id','x','y','direction','appearance','map_generation')}))
    if mode=='dialogue_start' and include_actions:
        seen_actions=set()
        for item in store.sessions:
            if not item.steps or not item.npc or not (item.observed_open or item.npc.get('touch')):continue
            for row in _action_observations(item,observed,seen_actions):
                if len(rows)>=MAX_COMPARISON_ROWS-len(starts):raise ValueError('比較観測が保持上限を超えています。')
                rows.append(row)
    arrivals = deepcopy(store.map_arrival_anchors)
    boundaries = {}
    boundary_rows = arrivals + [dict(kind='dialogue_start', capture_session=item.capture_session,
        flow_id=item.flow_id, packet_index=item.steps[0]['packet_index']) for item in store.sessions if item.steps]
    for other in boundary_rows:
        if mode == 'map_arrival' and other['kind'] != 'map_arrival':
            continue
        boundaries.setdefault((other['capture_session'], other['flow_id']), []).append(other['packet_index'])
    for indices in boundaries.values():
        indices.sort()
    for anchor in (starts if mode == 'dialogue_start' else arrivals):
        indices = boundaries.get((anchor['capture_session'], anchor['flow_id']), [])
        following = bisect_right(indices, anchor['packet_index'])
        if following < len(indices):
            anchor['end_after_packets'] = indices[following] - anchor['packet_index']
        rows.append(anchor)
    if len(rows) > MAX_COMPARISON_ROWS:
        raise ValueError('比較観測が保持上限を超えています。')
    return sorted(rows, key=lambda row: (row['capture_session'], row['packet_index'],
                                        0 if row.get('anchor_type') else 1))


def anchor_identity(row):
    npc = row.get('npc', {})
    if row.get('anchor_type') == 'map_arrival':
        if not npc.get('map_name') or npc.get('map_generation') is None:
            raise ValueError('MAPの取得根拠が必要です。')
        return dict(map_name=map_name(npc['map_name']), scope='map_arrival')
    fields = ('map_name', 'name', 'class_id', 'x', 'y', 'direction')
    if (row.get('entity_kind') != 'NPC' or not row.get('target_observed')
            or any(npc.get(key) is None for key in fields + ('appearance','map_generation'))
            or not npc.get('name') or not npc.get('map_name')):
        raise ValueError('基準点には対象と配置が判明したNPCを選択してください。')
    result = {key: npc[key] for key in fields}
    if row.get('anchor_type') == 'dialogue_start':
        result.update(map_name=map_name(npc['map_name']), name=npc_name(npc['name'], npc['map_name']),
                      class_id=declaration_class(npc))
        if projection(npc)['npc_suffix_status']=='ambiguous_partial':
            result['ambiguous_instance_scope']=dict(capture_session=row['capture_session'],flow_id=row['flow_id'],
                raw_map_name=npc['map_name'],actor_id=row['actor_id'])
    return result
