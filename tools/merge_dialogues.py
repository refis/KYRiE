"""Merge observed NPC menu paths conservatively from one or more raw logs."""
import argparse
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.auriga import AurigaRenderer
from reconstruction.branches import build_merged
from reconstruction.dialogue import Conversation
from tools.analyze_dialogues import analyze
from tools.cli_emulator import add_emulator_argument, apply_emulator, active_emulator


def merge(paths, definitions):
    sources = []
    protection = {}
    inferences = []
    def observations():
        nonlocal protection
        for path in sorted({Path(path).resolve() for path in paths}):
            report = analyze(path, definitions)
            sources.append(dict(source_log=str(path), replay=report['replay'],
                                definitions_sha256=report['definitions_sha256']))
            inferences.extend(report.get('touch_warp_inferences') or [])
            # Prefer a named character when multiple logs contribute identities.
            identity = dict(report.get('protection_identity') or {})
            if identity.get('character_name'):
                protection = identity
            elif not protection and identity:
                protection = identity
            for row in report['conversations']:
                yield str(path), Conversation(**row)
    result = build_merged(observations(), touch_inferences=inferences)
    renderer = AurigaRenderer(identity=protection)
    return dict(result, emulator=active_emulator(), sources=sources,
                protection_identity=protection,
                **renderer.render_groups(result['groups']))


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
    report = merge(args.logs, load_lengths(args.definitions))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Emulator {report["emulator"]}; NPC groups {len(report["groups"])}, '
          f'excluded conversations {len(report["excluded"])}, '
          f'input capacity reached {report["input_capacity_reached"]} -> {args.output}')
    if report['generation_errors']:
        print(f'Code generation stopped for {len(report["generation_errors"])} groups; observation JSON was saved')


if __name__ == '__main__':
    main()
