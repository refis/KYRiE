"""Bounded progress protocol observations; client reports never prove server success."""
from collections import OrderedDict, deque
from copy import deepcopy
import math


class ProgressTrace:
    def __init__(self,max_records=2000,max_pending=64):
        self.records=deque(maxlen=max_records);self.pending=OrderedDict()
        self.max_pending=max_pending;self.dropped=0;self.pending_evicted=0;self.capture_resets=0

    def begin_capture(self):
        self.capture_resets+=len(self.pending);self.pending.clear()

    def _record(self,event,session,index,kind,state=None,**extra):
        state=state or {};starts=state.get('starts',[])
        row=dict(kind=kind,capture_session=session,flow_id=event.flow_id or event.connection,
            packet_index=index,packet_id=event.packet_id,timestamp=event.timestamp,direction=event.direction,
            connection=event.connection,source=event.source,
            conversation_id=state.get('conversation_id'),conversation_actor_id=state.get('actor_id'),
            start_packet_index=starts[0] if len(starts)==1 and not state.get('ambiguous') else None,
            candidate_start_packets=list(starts),association_ambiguous=bool(state.get('ambiguous')),
            client_report_packet_index=state.get('response'),success_confirmed=False,cause_confirmed=False)
        if starts:
            when=state.get('timestamp')
            try:valid=type(when) in (int,float) and type(event.timestamp) in (int,float) and math.isfinite(when) and math.isfinite(event.timestamp) and event.timestamp>=when
            except OverflowError:valid=False
            elapsed = (event.timestamp-when)*1000 if valid else None
            row['observed_elapsed_ms'] = (round(elapsed, 3) if elapsed is not None
                and math.isfinite(elapsed) and not state.get('ambiguous') else None)
        row.update(extra)
        if len(self.records)==self.records.maxlen:self.dropped+=1
        self.records.append(row)
        return True

    def observe(self,event,session,index,conversation=None):
        key=(session,event.flow_id or event.connection);state=self.pending.get(key)
        pid=event.packet_id;direction=event.direction
        boundary=(direction=='SEND' and pid in (0x90,0x72,0x436) or direction=='RECV' and pid in (0x91,0x92))
        if state and boundary:
            self.pending.pop(key)
            return self._record(event,session,index,'progress_boundary',state)
        protocol=pid in (0x2f0,0x2f1,0x2f2)
        if protocol:
            expected=10 if pid==0x2f0 else 2
            expected_direction='SEND' if pid==0x2f1 else 'RECV'
            if len(event.raw)!=expected or direction!=expected_direction:
                self.pending.pop(key,None)
                return self._record(event,session,index,'progress_invalid',state,reason='unsupported_layout_or_direction')
            if pid==0x2f0:
                # A client report closes the previous start/report pair, without proving success.
                unresolved = state if state and state.get('response') is None else None
                starts=(unresolved.get('starts',[]) if unresolved else [])+[index]
                new=dict(starts=starts[-8:],timestamp=event.timestamp,ambiguous=bool(unresolved),
                    conversation_id=conversation.id if conversation else None,
                    actor_id=conversation.actor_id if conversation else None)
                self.pending[key]=new;self.pending.move_to_end(key)
                while len(self.pending)>self.max_pending:
                    self.pending.popitem(last=False);self.pending_evicted+=1
                return self._record(event,session,index,'progress_start',new,
                    fields=dict(color=int.from_bytes(event.raw[2:6],'little'),seconds=int.from_bytes(event.raw[6:10],'little')))
            if pid==0x2f2:
                self.pending.pop(key,None)
                return self._record(event,session,index,'progress_abort',state,orphan=state is None)
            changed=self._record(event,session,index,'progress_client_report',state,orphan=state is None,
                duplicate_client_report=bool(state and state.get('response') is not None),
                client_report_packet_index=index)
            if state and state.get('response') is None:state['response']=index
            return changed
        if (state and not state.get('ambiguous') and state.get('response') is not None and conversation
                and conversation.id==state.get('conversation_id') and conversation.actor_id==state.get('actor_id')
                and direction=='RECV' and pid in (0xb4,0x972,0xb5,0x973,0xb7,0xb6,0x8d6)):
            offset=4 if pid in (0xb4,0x972,0xb7) else 2
            if len(event.raw)>=offset+4 and int.from_bytes(event.raw[offset:offset+4],'little')==conversation.actor_id:
                self.pending.pop(key,None)
                return self._record(event,session,index,'progress_followup',state,
                    note='Same dialogue received a following notification; server success remains unverified.')
        return False

    def snapshot(self):
        return dict(observations=deepcopy(list(self.records)),dropped=self.dropped,pending_evicted=self.pending_evicted,
            capture_resets=self.capture_resets,pending=[dict(capture_session=key[0],flow_id=key[1],**deepcopy(state)) for key,state in self.pending.items()],
            success_inferred=False,server_timer_inferred=False)
