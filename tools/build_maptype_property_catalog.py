"""Build a MapTypeProperty catalog and comment-only mapflag hints (no per-map invent)."""
import argparse
import json
import os
import tempfile
from pathlib import Path

from reconstruction.maptype_property import build_catalog

ROOT = Path(__file__).resolve().parents[1]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--input', type=Path, required=True,
                     help='Path to MapTypeProperty.txt (reference; not committed)')
    cli.add_argument('--output', type=Path, default=ROOT / 'config/maptype_property_catalog.json')
    args = cli.parse_args()
    source = args.input.resolve()
    destination = args.output.resolve()
    if destination == source or destination.is_relative_to(ROOT / '.reference'):
        cli.error('Cannot overwrite reference or input files')
    document = build_catalog(source)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.json', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps(dict(
        output=str(destination), type_count=document['type_count'],
        parse_issues=len(document['parse_issues']),
        source_sha256=document['sources'][0]['sha256'],
        executable_mapflags=document['executable_mapflags'],
    ), ensure_ascii=False))


if __name__ == '__main__':
    main()
