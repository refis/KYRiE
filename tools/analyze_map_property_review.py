"""Replay a capture and write map_property manual-review analysis log."""
import argparse
import json
from pathlib import Path

from parser.definitions import load_lengths
from reconstruction.dialogue import DialogueStore
from reconstruction.world import WorldStore
from reconstruction.zc_mapproperty import summarize_review_rows
from tools.replay_capture import replay


def analyze(path, definitions):
    world = WorldStore()
    dialogues = DialogueStore(world=world)

    def consume(packet):
        world.apply(packet)
        dialogues.apply(packet, packet_index=consume.index)
        consume.index += 1

    consume.index = 0
    transport = replay(path, definitions, on_packet=consume)
    rows = [row for row in dialogues.presentation_observations if row.get('kind') == 'map_property']
    summary = summarize_review_rows(rows)
    return dict(
        source_log=str(Path(path).resolve()),
        replay=transport,
        map_property_count=len(rows),
        rows=[{
            'packet_index': row.get('packet_index'),
            'packet_id': row.get('packet_id'),
            'map_name': (row.get('map_context') or {}).get('map_name'),
            'fields': row.get('fields'),
            'manual_review': row.get('manual_review'),
        } for row in rows],
        summary=summary,
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from inputs')
    result = analyze(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    summary = result['summary']
    print(json.dumps(dict(
        map_property_count=result['map_property_count'],
        out_of_catalog=summary['out_of_catalog_count'],
        known_types=summary['known_type_count'],
        flag_memos=len(summary['flag_memos']),
        output=str(args.output),
    ), ensure_ascii=False))


if __name__ == '__main__':
    main()
