"""Compare observed input-free dialogue intervals across raw capture logs."""
import argparse
import json
from pathlib import Path

from parser.definitions import load_lengths
from reconstruction.timing import summarize_timings
from tools.analyze_dialogues import analyze
from tools.cli_emulator import add_emulator_argument, apply_emulator, active_emulator


def compare(paths, definitions):
    unique = sorted({Path(path).resolve() for path in paths})
    timelines, sources = [], []
    for path in unique:
        result = analyze(path, definitions)
        timelines.extend(result['timelines'])
        sources.append(dict(source_log=str(path), definitions_sha256=result['definitions_sha256'],
                            replay=result['replay'], issue_count=result['issue_count']))
    return dict(emulator=active_emulator(), sources=sources, timelines=timelines,
                summary=summarize_timings(timelines))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('logs', nargs='+', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    add_emulator_argument(cli)
    args = cli.parse_args()
    if args.output.resolve() in {path.resolve() for path in [*args.logs, args.definitions]}:
        cli.error('Output must differ from input logs and definitions')
    apply_emulator(args.emulator)
    report = compare(args.logs, load_lengths(args.definitions))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Emulator {report["emulator"]}; sources {len(report["sources"])}, '
          f'conversations {len(report["timelines"])}, '
          f'comparison groups {len(report["summary"]["groups"])} -> {args.output}')


if __name__ == '__main__':
    main()
