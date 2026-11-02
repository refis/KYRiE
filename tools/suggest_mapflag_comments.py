"""Emit review-only mapflag comment lines for an observed map name + 01D6/099B type."""
import argparse
import json
from pathlib import Path

from reconstruction.maptype_property import suggest_mapflag_comments

ROOT = Path(__file__).resolve().parents[1]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--catalog', type=Path, default=ROOT / 'config/maptype_property_catalog.json')
    cli.add_argument('--map', required=True, help='Map name as observed (with or without .gat)')
    cli.add_argument('--type', type=int, required=True, help='Wire map type / MAPTYPE number')
    cli.add_argument('--json', action='store_true', help='Print structured result instead of comments')
    args = cli.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding='utf-8'))
    result = suggest_mapflag_comments(catalog, args.map, args.type)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for line in result['comments']:
        print(line)


if __name__ == '__main__':
    main()
