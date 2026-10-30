"""Extract bounded inventory-layout evidence without guessing unknown flag offsets."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.player import LIST_STRIDES,decode_player
from reconstruction.decoder import ObservationError
from storage.project import fingerprint
from storage.observation_export import save_observations
from tools.replay_capture import replay


class InventoryLayoutAudit:
    SAMPLE_LIMIT=32
    ROW_LIMIT=8
    def __init__(self):
        self.layouts={f'0x{pid:04X}':dict(stride=stride,packets=0,valid_packets=0,entries=0,
            other_inventory_packets=0,invalid_packets=0,samples=[],samples_omitted=0)
            for pid,stride in LIST_STRIDES.items()}

    def observe(self,event,packet_index):
        if event.direction!='RECV' or event.packet_id not in LIST_STRIDES:return
        record=self.layouts[f'0x{event.packet_id:04X}'];record['packets']+=1
        sample=dict(packet_index=packet_index,timestamp=event.timestamp,connection=event.connection,
            flow_id=event.flow_id,packet_bytes=len(event.raw),raw_sha256=hashlib.sha256(event.raw).hexdigest())
        try:
            kind,fields=decode_player(event)
            if kind=='other_inventory':
                record['other_inventory_packets']+=1
                sample.update(status='other_inventory',inventory_type=fields['inventory_type'])
            else:
                record['valid_packets']+=1;record['entries']+=fields['entries']
                stride=record['stride'];rows=[]
                for i,(index,item) in enumerate(fields['items'].items()):
                    if i>=self.ROW_LIMIT:break
                    rows.append(dict(record_index=i,index=index,item_id=item['item_id'],amount=item['amount'],
                        identified=item['identified'],inventory_flags=item['inventory_flags'],
                        raw_hex=event.raw[5+i*stride:5+(i+1)*stride].hex()))
                sample.update(status='decoded',entries=fields['entries'],rows=rows,
                    rows_omitted=max(0,fields['entries']-len(rows)),
                    identification_layout='unconfirmed' if event.packet_id==0xb38 else 'verified_bit0')
        except ObservationError as exc:
            record['invalid_packets']+=1
            sample.update(status='invalid',error=str(exc),raw_prefix_hex=event.raw[:128].hex())
        if len(record['samples'])<self.SAMPLE_LIMIT:record['samples'].append(sample)
        else:record['samples_omitted']+=1

    def snapshot(self):
        return deepcopy(dict(kind='inventory_layout_evidence',layouts=self.layouts,
            sample_limit_per_layout=self.SAMPLE_LIMIT,row_limit_per_sample=self.ROW_LIMIT,
            unknown_flag_offsets_inferred=False,player_state_modified=False))


def analyze(path,definitions_path):
    path=Path(path).resolve();definitions_path=Path(definitions_path).resolve()
    source_hash=fingerprint(path,128*1024*1024);definition_hash=fingerprint(definitions_path,2*1024*1024)
    audit=InventoryLayoutAudit();count=0
    def consume(event):
        nonlocal count
        audit.observe(event,count);count+=1
    transport=replay(path,load_lengths(definitions_path),on_packet=consume,
        max_line_chars=2*1024*1024,max_input_chars=128*1024*1024)
    if (fingerprint(path,128*1024*1024)!=source_hash
            or fingerprint(definitions_path,2*1024*1024)!=definition_hash):
        raise ValueError('Audit input changed')
    return dict(audit.snapshot(),source=str(path),source_sha256=source_hash,
                definitions=str(definitions_path),definitions_sha256=definition_hash,
                packet_count=count,transport=transport)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log',type=Path);cli.add_argument('--definitions',type=Path)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    definitions=args.definitions or args.log.with_name('PacketLength.used.txt')
    if not definitions.is_file():cli.error('Specify --definitions or use a recorded PacketLength.used.txt')
    save_observations(args.output,analyze(args.log,definitions),[args.log,definitions])
    print(str(args.output))


if __name__=='__main__':main()
