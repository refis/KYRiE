"""Preview or apply static skillinfoz names; differing Lua names win."""
import argparse
from pathlib import Path
from reconstruction.skill_catalog import build_import, apply_import, REFERENCE_ROOT
from reconstruction.skills import DEFAULT_NAMES
from storage.observation_export import save_observations

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / '.reference/data/luafiles514/lua files/skillinfoz'


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--skillid', type=Path, default=DEFAULT_SOURCE/'skillid.lua')
    cli.add_argument('--info', type=Path, default=DEFAULT_SOURCE/'skillinfolist.lua')
    cli.add_argument('--dictionary', type=Path, default=DEFAULT_NAMES)
    cli.add_argument('--encoding', choices=('cp932','utf-8'), default='cp932')
    cli.add_argument('--report', type=Path)
    cli.add_argument('--apply', action='store_true', help='Apply validated names atomically; default is dry-run')
    args = cli.parse_args()
    try:
        document, report = build_import(args.skillid,args.info,args.dictionary,args.encoding)
        if args.report:
            if args.report.resolve().is_relative_to(REFERENCE_ROOT.resolve()):
                raise ValueError('Reference data is read-only')
            save_observations(args.report,report,[row['path'] for row in report['inputs']])
        print(f"Names {report['before_count']} -> {report['result_count']}; "
              f"add {len(report['additions'])}; change {len(report['changes'])}; "
              f"retain {len(report['retained_existing_ids'])}; issues {len(report['issues'])}")
        if not report['ready']:
            cli.error('Import has unresolved or invalid records; dictionary unchanged')
        if args.apply:
            print('Applied SHA256 '+apply_import(document,report))
        else:
            print('Dry-run: dictionary unchanged')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        cli.error(str(exc))


if __name__ == '__main__':
    main()
