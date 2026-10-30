"""Replay a recorded capture to inspect self-player public-chat evidence only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.world import WorldStore
from reconstruction.speech_origin import SpeechOrigin, payload
from storage.project import fingerprint
from storage.observation_export import save_observations
from tools.replay_capture import replay


def audit(log, definitions, max_details=1000):
    if type(max_details) is not int or not 1<=max_details<=1000:
        raise ValueError('Detail limit must be 1..1000')
    log,definitions=Path(log).resolve(),Path(definitions).resolve()
    source_hash=fingerprint(log,128*1024*1024)
    definition_hash=fingerprint(definitions,2*1024*1024)
    lengths=load_lengths(definitions)
    world=WorldStore();tracker=SpeechOrigin()
    packets=Counter();origins=Counter();reasons=Counter();details=[]
    index=0;invalid_sends=0;receives=0
    def consume(event):
        nonlocal index,invalid_sends,receives
        number=index;index+=1
        world.apply(event,packet_index=number)
        if event.packet_id not in (0x8c,0x8d,0x8e,0x8b3):return
        packets[f'{event.direction} 0x{event.packet_id:04X}']+=1
        state=world.player_maps.states.get((0,event.flow_id or event.connection))
        self_actor=state.actor_id if state else None
        if event.direction=='SEND' and event.packet_id==0x8c:
            invalid_sends+=payload(event) is None
            tracker.sent(event,0,number,self_actor)
        if event.direction!='RECV' or event.packet_id not in (0x8d,0x8e,0x8b3):return
        receives+=1
        actor=(int.from_bytes(event.raw[4:8],'little') if len(event.raw)>=8 else None) if event.packet_id in (0x8d,0x8b3) else self_actor
        evidence=tracker.received(event,0,number,actor,self_actor)
        origins[evidence['origin']]+=1;reasons[evidence['reason']]+=1
        body=payload(event)
        if len(details)<max_details:
            details.append(dict(packet_index=number,packet_id=event.packet_id,flow_id=event.flow_id or event.connection,
                actor_id=actor,self_actor_id=self_actor,payload_supported=body is not None,
                payload_sha256=hashlib.sha256(body).hexdigest() if body is not None else None,
                speech_origin=evidence))
    transport=replay(log,lengths,on_packet=consume)
    if fingerprint(log,128*1024*1024)!=source_hash or fingerprint(definitions,2*1024*1024)!=definition_hash:
        raise ValueError('Audit input changed during replay')
    return dict(kind='player_speech_replay_audit',source_log=str(log),source_sha256=source_hash,
        definitions=str(definitions),definitions_sha256=definition_hash,packet_count=index,
        speech_packets=dict(packets),receive_origin_counts=dict(origins),receive_reason_counts=dict(reasons),
        unsupported_send_layouts=invalid_sends,details=details,omitted_details=receives-len(details),
        replay=transport,cause_confirmed=False,script_origin_inferred=False,live_input_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log');parser.add_argument('--definitions',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report=audit(args.log,args.definitions)
    save_observations(args.output,report,[args.log,args.definitions])
    print(json.dumps({key:report[key] for key in ('packet_count','speech_packets','receive_origin_counts','receive_reason_counts','unsupported_send_layouts','omitted_details')}))


if __name__=='__main__':main()
