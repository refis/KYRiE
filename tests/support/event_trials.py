def observation(time, value=7, **changes):
    row = dict(capture_session=0, flow_id='flow', actor_id=42, entity_kind='NPC', target_observed=True,
        kind='emotion', fields=dict(value=value), context='outside_dialogue', timestamp=time,
        packet_index=round(time * 100), connection='receive',
        npc=dict(map_name='test.gat', name='NPC', class_id=45, x=10, y=20, direction=0,
                 map_generation=1, appearance=1))
    row.update(changes)
    return row


def repeated_report(followup_kind='emotion'):
    from reconstruction.event_trials import compare_event_trials
    rows = [observation(0), observation(1, 9, kind=followup_kind),
            observation(10), observation(11, 9, kind=followup_kind),
            observation(20), observation(21, 9, kind=followup_kind)]
    return compare_event_trials(rows, [0, 2, 4], window_ms=2000, source_sessions={0: 'capture.jsonl'})


def instance_action_store():
    from types import SimpleNamespace
    from tests.support.branches import conversation
    items=[]
    for number,token in enumerate(('aB1','cD2','eF3'),1):
        item=conversation(identifier=number,actor=1000+number)
        item.capture_session=number;item.flow_id='flow-'+str(number);item.started=0
        item.npc.update(name='Owner_'+token,map_name=token+'1@toy.gat',map_generation=number,appearance=1)
        for index,step in enumerate(item.steps):step.update(timestamp=index*.1,packet_index=number*100+index*10)
        item.actions=[dict(kind='visibility_action',fields=dict(commands=['hideonnpc'],
            target=dict(name='Target_'+token,map_name=token+'1@toy.gat'),options=2,previous_options=0),
            capture_session=number,flow_id=item.flow_id,timestamp=.15,packet_index=number*100+15,
            packet_id=0x229,direction='RECV',connection='receive-'+str(number),source='TEST',
            after_step_index=1,cause_confirmed=False)]
        items.append(item)
    return SimpleNamespace(sessions=items,presentation_observations=[],map_arrival_anchors=[])


def player_notification_trial(session, text='notice', choice=1):
    from dataclasses import asdict
    from tests.support.branches import conversation
    item=conversation(choice=choice,identifier=1)
    item.capture_session=session;item.flow_id=f'flow-{session}';item.started=0
    for index,step in enumerate(item.steps):step.update(packet_index=session*100+index*10,timestamp=index*.1)
    close=len(item.steps)-1;reply=len(item.steps)
    item.steps[close]['reply']=reply
    item.steps.append(dict(kind='dismiss',fields={},reply_to=close,packet_index=session*100+reply*10,
        timestamp=reply*.1,packet_id=0x146,direction='SEND',connection='half',source='TEST'))
    contribution=dict(conversation=asdict(item),source_ref=f'capture-{session}.jsonl')
    rows=[] if text is None else [dict(kind='overhead',packet_id=0x8b3,direction='RECV',
        capture_session=session,flow_id=item.flow_id,conversation_id=item.id,conversation_actor_id=item.actor_id,
        entity_kind='PLAYER',actor_id=9000+session,npc={},context='during_dialogue',after_step_index=1,
        packet_index=session*100+15,timestamp=.15,fields={'text':text},cause_confirmed=False,
        association_basis='active_dialogue_same_flow_player_notification',
        speech_origin=dict(origin='unresolved',reason='non_chat_notification',self_actor_confirmed=True,association_only=True))]
    return contribution,rows
