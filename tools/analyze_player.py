"""Rebuild basic player data from an opt-in raw capture log."""
import argparse
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.player import PlayerStore
from tools.replay_capture import replay


def analyze(path, definitions):
    store = PlayerStore()
    count = 0
    def consume(event):
        nonlocal count
        store.apply(event, packet_index=count)
        count += 1
    transport = replay(path, definitions, on_packet=consume)
    return dict(store.snapshot(), source_log=str(Path(path).resolve()), replay=transport)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from log and definitions')
    result = analyze(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Player flows {len(result["states"])}, observation issues {result["issue_count"]} -> {args.output}')


if __name__ == '__main__':
    main()
