"""Merge observed NPC menu paths conservatively from one or more raw logs."""
import argparse
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.dialogue import Conversation
from tools.analyze_dialogues import analyze


def merge(paths, definitions):
    sources = []
    def observations():
        for path in sorted({Path(path).resolve() for path in paths}):
            report = analyze(path, definitions)
            sources.append(dict(source_log=str(path), replay=report['replay'],
                                definitions_sha256=report['definitions_sha256']))
            for row in report['conversations']:
                yield str(path), Conversation(**row)
    result = build_merged(observations())
    renderer = AurigaRenderer()
    return dict(result, sources=sources, **renderer.render_groups(result['groups']))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('logs', nargs='+', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    if args.output.resolve() in {path.resolve() for path in [*args.logs, args.definitions]}:
        cli.error('Output must differ from input logs and definitions')
    report = merge(args.logs, load_lengths(args.definitions))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'NPC groups {len(report["groups"])}, excluded conversations {len(report["excluded"])}, '
          f'input capacity reached {report["input_capacity_reached"]} -> {args.output}')
    if report['generation_errors']:
        print(f'Code generation stopped for {len(report["generation_errors"])} groups; observation JSON was saved')


if __name__ == '__main__':
    main()
