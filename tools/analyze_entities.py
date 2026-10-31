"""Build reproducible NPC/MOB observation state from an opt-in raw capture log."""
import argparse
import hashlib
import json
from pathlib import Path

from parser.definitions import load_lengths
from reconstruction.world import WorldStore
from reconstruction.mob_spawns import MobSpawnStore
from reconstruction.mob_spawn_export import build_candidates, render_candidates
from reconstruction.entity_metadata import build_metadata_report
from tools.cli_emulator import add_emulator_argument, apply_emulator, active_emulator
from tools.replay_capture import replay


def analyze(path, definitions):
    world = WorldStore()
    spawns = MobSpawnStore(world)
    index = 0
    def consume(packet):
        nonlocal index
        world.apply(packet, packet_index=index)
        spawns.apply(packet, packet_index=index)
        index += 1
    transport = replay(path, definitions, on_packet=consume)
    result = world.snapshot()
    definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
    result.update(emulator=active_emulator(), source_log=str(path),
                  definitions_sha256=hashlib.sha256(definition_text.encode('utf-8')).hexdigest(),
                  replay=transport, entity_counts={kind: len(world.records(kind)) for kind in ('NPC', 'MOB')})
    result['mob_spawn_observations'] = spawns.snapshot()
    result['auriga_spawn_candidates'] = build_candidates(result['mob_spawn_observations'], {0: str(Path(path).resolve())})
    result['auriga_spawn_review'] = render_candidates(result['auriga_spawn_candidates'])
    result['entity_metadata'] = build_metadata_report(result['entities'])
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    add_emulator_argument(cli)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from log and definitions')
    apply_emulator(args.emulator)
    result = analyze(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Emulator {result["emulator"]}; NPC {result["entity_counts"]["NPC"]}, '
          f'MOB {result["entity_counts"]["MOB"]}, '
          f'observation issues {result["issue_count"]} -> {args.output}')


if __name__ == '__main__':
    main()
