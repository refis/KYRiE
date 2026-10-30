"""Reconstruct observed NPC conversation paths from a raw opt-in capture."""
import argparse
import hashlib
import json
from pathlib import Path

from parser.definitions import load_lengths
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged, observation_key
from reconstruction.dialogue import DialogueStore
from reconstruction.world import WorldStore
from reconstruction.player import PlayerStore
from tools.replay_capture import replay


def analyze(path, definitions):
    world = WorldStore()
    store = DialogueStore(world=world)
    players = PlayerStore()
    def consume(packet):
        world.apply(packet)
        values = players.apply(packet)
        store.apply(packet, player_observation=values)
    transport = replay(path, definitions, on_packet=consume)
    result = store.snapshot(source_ref=str(Path(path).resolve()))
    definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
    result.update(source_log=str(path), replay=transport,
                  definitions_sha256=hashlib.sha256(definition_text.encode('utf-8')).hexdigest())
    renderer = AurigaRenderer()
    source = str(Path(path).resolve())
    merged = build_merged((source, conversation) for conversation in store.sessions)
    checks = {(ref['source_ref'], ref['capture_session'], ref['conversation_id']): group['presentation_check']
              for group in merged['groups'] for ref in group['contributions']
              }
    result['presentation_checks'] = [dict(npc=group['npc'], **group['presentation_check'])
                                     for group in merged['groups']]
    result['auriga'] = [renderer.render(conversation, checks.get(observation_key(source, conversation)))
                        for conversation in store.sessions]
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from log and definitions')
    result = analyze(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Conversations {len(result["conversations"])}, issues {result["issue_count"]} -> {args.output}')


if __name__ == '__main__':
    main()
