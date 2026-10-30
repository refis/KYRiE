"""Replay normal-shop lists and retain client IDs, prices and target evidence."""
import argparse
import json
from pathlib import Path

from parser.definitions import load_lengths
from reconstruction.world import WorldStore
from reconstruction.shops import ShopStore
from reconstruction.dialogue import DialogueStore
from reconstruction.player import PlayerStore
from dataclasses import asdict
from tools.replay_capture import replay


def analyze(path, definitions):
    world = WorldStore()
    dialogues = DialogueStore(world=world)
    players = PlayerStore()
    store = ShopStore(world, dialogues=dialogues)
    def consume(packet):
        world.apply(packet)
        store.apply(packet, packet_index=consume.index)
        values = players.apply(packet, packet_index=consume.index)
        dialogues.apply(packet, packet_index=consume.index, player_observation=values)
        consume.index += 1
    consume.index = 0
    transport = replay(path, definitions, on_packet=consume)
    linked = {(row['capture_session'], row['conversation_id']) for row in store.records}
    return dict(store.snapshot(), source_log=str(Path(path).resolve()), replay=transport,
                conversations=[asdict(item) for item in dialogues.sessions if (item.capture_session, item.id) in linked])


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
    print(f'Shop lists {len(result["records"])}, issues {result["issue_count"]}')


if __name__ == '__main__':
    main()
