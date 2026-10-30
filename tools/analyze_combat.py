"""Rebuild observed MOB attack, damage, speed and HP information from raw logs."""
import argparse
import hashlib
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.world import WorldStore
from reconstruction.combat import CombatStore
from tools.replay_capture import replay


def analyze(path, definitions):
    world = WorldStore()
    store = CombatStore(world)
    index = 0
    def consume(packet):
        nonlocal index
        world.apply(packet, packet_index=index)
        store.apply(packet, packet_index=index)
        index += 1
    transport = replay(path, definitions, consume)
    definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
    return dict(store.snapshot(), source_log=str(Path(path).resolve()), replay=transport,
                definitions_sha256=hashlib.sha256(definition_text.encode()).hexdigest())


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from log and definitions')
    report = analyze(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'MOB performance observations {len(report["observations"])}, classes {len(report["class_performance"])}, '
          f'issues {report["issue_count"]} -> {args.output}')


if __name__ == '__main__':
    main()
