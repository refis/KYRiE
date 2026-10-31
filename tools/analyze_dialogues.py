"""Reconstruct observed NPC conversation paths from a raw opt-in capture."""
import argparse
import hashlib
from pathlib import Path

from parser.definitions import load_lengths
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged, observation_key
from reconstruction.dialogue import DialogueStore
from reconstruction.world import WorldStore
from reconstruction.player import PlayerStore
from tools.replay_capture import replay
from storage.project import fingerprint
from storage.observation_export import save_observations,validate_export_destination


def analyze(path, definitions):
    path=Path(path).resolve()
    source_hash=fingerprint(path,128*1024*1024)
    world = WorldStore()
    store = DialogueStore(world=world)
    players = PlayerStore()
    def consume(packet):
        world.apply(packet)
        values = players.apply(packet)
        store.apply(packet, player_observation=values)
    transport = replay(path, definitions, on_packet=consume,
                       max_line_chars=2*1024*1024,max_input_chars=128*1024*1024)
    result = store.snapshot(source_ref=str(Path(path).resolve()))
    definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
    result.update(source_log=str(path), source_sha256=source_hash, replay=transport,
                  definitions_sha256=hashlib.sha256(definition_text.encode('utf-8')).hexdigest())
    from reconstruction.identity_protection import identity_for_connection
    source = str(Path(path).resolve())
    merged = build_merged((source, conversation) for conversation in store.sessions)
    checks = {(ref['source_ref'], ref['capture_session'], ref['conversation_id']): group['presentation_check']
              for group in merged['groups'] for ref in group['contributions']
              }
    result['presentation_checks'] = [dict(npc=group['npc'], **group['presentation_check'])
                                     for group in merged['groups']]
    result['auriga'] = [
        AurigaRenderer(identity=identity_for_connection(
            players, conversation.capture_session, conversation.flow_id)).render(
            conversation, checks.get(observation_key(source, conversation)))
        for conversation in store.sessions]
    if fingerprint(path,128*1024*1024)!=source_hash:
        raise ValueError('解析中に生ログが変更されました。取得停止後に再実行してください。')
    return result


def save_report(path,report,definitions_path):
    save_observations(path,report,[report['source_log'],definitions_path])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    validate_export_destination(args.output,[args.log,args.definitions])
    definition_hash=fingerprint(args.definitions,2*1024*1024)
    result = analyze(args.log, load_lengths(args.definitions))
    if fingerprint(args.definitions,2*1024*1024)!=definition_hash:
        raise ValueError('Length definitions changed during analysis')
    result.update(definitions_path=str(args.definitions.resolve()),definitions_file_sha256=definition_hash)
    save_report(args.output,result,args.definitions)
    print(f'Conversations {len(result["conversations"])}, issues {result["issue_count"]} -> {args.output}')


if __name__ == '__main__':
    main()
