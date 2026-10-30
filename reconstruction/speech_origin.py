"""Bounded exact-byte public-chat associations; missing SEND never proves script origin."""
from collections import deque
import math


def payload(packet):
    offset = 8 if packet.packet_id in (0x8d, 0x8b3) else 4
    raw = packet.raw
    if not offset < len(raw) <= 1024 or int.from_bytes(raw[2:4], 'little') != len(raw):
        return None
    text = raw[offset:]
    if text.endswith(b'\0'):
        text = text[:-1]
    elif packet.packet_id not in (0x8c, 0x8e):
        return None
    if b'\0' in text:
        return None
    return text


class SpeechOrigin:
    def __init__(self):
        self.pending = deque(maxlen=64)

    def sent(self, packet, session, index, actor):
        if packet.packet_id != 0x8c or packet.direction != 'SEND':return
        text=payload(packet)
        if text is not None:
            self.pending.append((session, packet.flow_id or packet.connection, index,
                                 packet.timestamp, actor, text))

    def received(self, packet, session, index, actor, self_actor):
        text=payload(packet)
        result=dict(origin='unresolved',reason='no_matching_send',self_actor_confirmed=self_actor is not None and actor==self_actor,
                    cause_confirmed=False,association_only=True)
        if text is None:
            result['reason']='unsupported_layout';return result
        if self_actor is None:
            result['reason']='self_actor_unknown';return result
        if actor!=self_actor:
            result['reason']='different_actor';return result
        if packet.packet_id == 0x8b3:
            result['reason']='non_chat_notification';return result
        matches=[]
        for item in self.pending:
            generation,flow,number,when,owner,content=item
            if generation!=session or flow!=(packet.flow_id or packet.connection) or owner!=self_actor or content!=text or number>=index:
                continue
            try:valid=type(when) in (int,float) and type(packet.timestamp) in (int,float) and math.isfinite(when) and math.isfinite(packet.timestamp) and 0<=packet.timestamp-when<=5
            except OverflowError:valid=False
            if valid:matches.append(item)
        if matches:
            for item in matches:self.pending.remove(item)
        if len(matches)==1:
            result.update(origin='send_match_candidate',reason='unique_send_match',send_packet_index=matches[0][2],
                          send_packet_id=0x8c,match_basis='same_capture_flow_self_actor_exact_bytes_order_within_5s')
        elif len(matches)>1:result.update(origin='ambiguous_send_candidates',reason='multiple_matching_sends',candidate_count=len(matches))
        return result


def index_player_notifications(rows):
    from collections import defaultdict
    result=defaultdict(list)
    for row in rows:
        if (row.get('association_basis')=='active_dialogue_same_flow_player_notification'
                and row.get('entity_kind')=='PLAYER'):
            result[(row.get('capture_session'),row.get('flow_id'),row.get('conversation_id'),row.get('conversation_actor_id'))].append(row)
    return result


def linked_player_notifications(conversation, indexed):
    import json
    result=[];seen=set()
    key=(conversation.capture_session,conversation.flow_id,conversation.id,conversation.actor_id)
    for row in indexed.get(key,()):
        index=row.get('after_step_index');number=row.get('packet_index')
        if (row.get('kind')!='overhead' or row.get('packet_id')!=0x8b3 or row.get('direction')!='RECV'
                or row.get('actor_id')==conversation.actor_id
                or row.get('context') not in ('during_dialogue','input_wait','close_wait')
                or type(index) is not int or not 0<=index<len(conversation.steps)
                or type(number) is not int or number<=conversation.steps[index]['packet_index']):continue
        if index+1<len(conversation.steps) and number>=conversation.steps[index+1]['packet_index']:
            continue
        signature=json.dumps(row,sort_keys=True,ensure_ascii=True)
        if signature not in seen:seen.add(signature);result.append(row)
    return result
