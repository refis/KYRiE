"""Build MAPTYPE/MAPPROPERTY symbol catalog from PACKET_ZC_MAPPROPERTY.txt."""
import argparse
import json
import os
import tempfile
from pathlib import Path

from reconstruction.zc_mapproperty import build_zc_symbols

ROOT = Path(__file__).resolve().parents[1]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--input', type=Path, required=True)
    cli.add_argument('--output', type=Path, default=ROOT / 'config/zc_mapproperty_symbols.json')
    args = cli.parse_args()
    source = args.input.resolve()
    destination = args.output.resolve()
    if destination == source or destination.is_relative_to(ROOT / '.reference'):
        cli.error('Cannot overwrite reference or input files')
    document = build_zc_symbols(source)
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
        output=str(destination),
        maptypes=len(document['maptypes']),
        properties=len(document['properties']),
        samples=len(document['samples']),
        source_sha256=document['sources'][0]['sha256'],
    ), ensure_ascii=False))


if __name__ == '__main__':
    main()
