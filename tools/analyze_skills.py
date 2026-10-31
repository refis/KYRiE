"""Reconstruct per-individual MOB skill observations from raw capture logs."""
import argparse
import hashlib
import json
from pathlib import Path
from parser.definitions import load_lengths
from reconstruction.world import WorldStore
from reconstruction.skills import SkillStore, load_skill_names
from tools.replay_capture import replay
from tools.cli_emulator import add_emulator_argument, apply_emulator, active_emulator
from reconstruction.mob_skill_export import build_candidates, render_candidates


def analyze(path, definitions):
    world = WorldStore()
    store = SkillStore(world)
    index = 0
    def consume(packet):
        nonlocal index
        world.apply(packet, packet_index=index)
        store.apply(packet, packet_index=index)
        index += 1
    transport = replay(path, definitions, consume)
    report = store.snapshot()
    definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
    report.update(emulator=active_emulator(), source_log=str(Path(path).resolve()), replay=transport,
                  definitions_sha256=hashlib.sha256(definition_text.encode()).hexdigest())
    try:
        report['skill_names'] = {str(key): value for key, value in load_skill_names().items()}
    except (OSError, ValueError) as exc:
        report.update(skill_names={}, dictionary_error=str(exc))
    report['auriga_candidates'] = build_candidates(report, report['skill_names'], {0: str(Path(path).resolve())})
    report['auriga_review'] = render_candidates(report['auriga_candidates'])
    return report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    add_emulator_argument(cli)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from log and definitions')
    apply_emulator(args.emulator)
    report = analyze(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Emulator {report["emulator"]}; MOB skill notifications {len(report["observations"])}, '
          f'class skills {len(report["class_skills"])}, '
          f'issues {report["issue_count"]} -> {args.output}')


if __name__ == '__main__':
    main()
