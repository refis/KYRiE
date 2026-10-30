"""Read-only self-notification differences for complete, identical observed dialogue paths."""
from copy import deepcopy
import hashlib
import json
import math
from reconstruction.dialogue import Conversation
from reconstruction.branches import conversation_path, npc_identity
from reconstruction.timing import build_timeline
from reconstruction.touch import is_touch
from reconstruction.speech_origin import index_player_notifications, linked_player_notifications


def review_player_notification_repeats(contributions, rows, sources=None):
    contributions=list(contributions)
    if len(contributions)>2000:raise ValueError('本人通知の比較は2000観測以内にしてください。')
    sources=sources or {};indexed=index_player_notifications(rows)
    result=dict(kind='player_notification_repeat_review',groups=[],excluded=[],duplicate_observations=0,
        cause_confirmed=False,missing_packet_inferred=False,command_generation=False,
        capture_completeness='not_verified',time_comparison=False)
    if not indexed:return result
    groups={};seen=set();steps=0
    for contribution in contributions:
        data=contribution['conversation'];session=data['capture_session']
        current=sources.get(session,sources.get(str(session),''));source=contribution.get('source_ref','')
        reference=dict(source_ref=source or current,capture_session=session,conversation_id=data['id'],flow_id=data['flow_id'])
        if current and source and current!=source:
            result['excluded'].append(dict(reference,reason='source_mismatch'));continue
        key=(reference['source_ref'],session,data['id'],data['flow_id'],data['actor_id'])
        if key in seen:result['duplicate_observations']+=1;continue
        seen.add(key)
        steps+=len(data.get('steps',[]))
        if steps>100000:raise ValueError('本人通知の比較は合計100000ステップ以内にしてください。')
        try:
            item=Conversation(**data)
            if item.status not in ('closed','map_changed','shop_opened'):
                raise ValueError('incomplete_conversation')
            if any(step.get('timeout_suspected') for step in item.steps):
                raise ValueError('unanswered_termination')
            timing=build_timeline(item)
            flags=set(timing['quality_flags'])-({'start_unobserved'} if is_touch(item.npc) else set())
            if flags:raise ValueError('observation_quality')
            if any(not wait['complete'] for wait in timing['waits']):raise ValueError('incomplete_wait')
            identity=npc_identity(item,reference['source_ref'])
            if identity is None:raise ValueError('npc_identity_incomplete')
            tokens=conversation_path(reference['source_ref'],item)
            semantic_path=[identity,[(step['kind'],step.get('fields',{})) for step in item.steps],
                           [(token['kind'],token['fields']) for token in tokens]]
            path=json.dumps(semantic_path,sort_keys=True,ensure_ascii=True,allow_nan=False)
            notices=sorted(linked_player_notifications(item,indexed),key=lambda row:row['packet_index'])
            raw=indexed.get((item.capture_session,item.flow_id,item.id,item.actor_id),())
            if len({json.dumps(row,sort_keys=True,ensure_ascii=True) for row in raw})!=len(notices):
                raise ValueError('notification_scope_or_order')
            if any(type(row.get('actor_id')) is not int or row['actor_id']<=0
                    or row.get('speech_origin',{}).get('self_actor_confirmed') is not True for row in notices):
                raise ValueError('self_actor_unconfirmed')
            if any(row.get('speech_origin',{}).get('reason')!='non_chat_notification' for row in notices):
                raise ValueError('notification_origin_unconfirmed')
            for row in notices:
                when=row.get('timestamp');anchor=row['after_step_index']
                try:
                    valid=type(when) in (int,float) and math.isfinite(when) and when>=item.steps[anchor]['timestamp']
                except OverflowError:valid=False
                if not valid or (anchor+1<len(item.steps) and when>item.steps[anchor+1]['timestamp']):
                    raise ValueError('notification_time_invalid')
            if len({row['packet_index'] for row in notices})!=len(notices):
                raise ValueError('conflicting_notification_evidence')

            if len(notices)>1000:raise ValueError('notification_limit')
        except (ValueError,TypeError,KeyError) as exc:
            reason=str(exc) if isinstance(exc,ValueError) else 'invalid_observation'
            result['excluded'].append(dict(reference,reason=reason));continue
        sequence=[dict(after_step_index=row['after_step_index'],context=row['context'],kind=row['kind'],fields=deepcopy(row['fields'])) for row in notices]
        observation=dict(reference,actor_id=item.actor_id,notification_count=len(notices),
            notifications=[dict(value,packet_index=row['packet_index'],target_actor_id=row['actor_id'],
                preceding_packet_index=item.steps[row['after_step_index']]['packet_index']) for value,row in zip(sequence,notices)])
        group=groups.setdefault(path,dict(path_sha256=hashlib.sha256(path.encode('ascii')).hexdigest(),
            npc_identity=identity,observations=[],variants={}))
        number=len(group['observations']);group['observations'].append(observation)
        signature=json.dumps(sequence,sort_keys=True,ensure_ascii=True,allow_nan=False)
        group['variants'].setdefault(signature,dict(sequence=sequence,observation_indices=[]))['observation_indices'].append(number)
    for group in groups.values():
        if not any(row['notification_count'] for row in group['observations']):continue
        group['variants']=list(group['variants'].values())
        group['status']=('insufficient_observations' if len(group['observations'])<2 else
                         'observed_match' if len(group['variants'])==1 else 'observed_difference')
        result['groups'].append(group)
    return result
