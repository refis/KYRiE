"""One-pass, evidence-preserving session analysis for offline verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter

from parser.definitions import load_lengths
from reconstruction.world import WorldStore
from reconstruction.actor_appearance import JOB_IDS_PATH, render_display
from reconstruction.player import PlayerStore
from reconstruction.dialogue import DialogueStore
from reconstruction.script_commands import render_command
from reconstruction.shops import ShopStore
from reconstruction.barter import BarterStore
from reconstruction.combat import CombatStore
from reconstruction.skills import SkillStore
from reconstruction.mob_spawns import MobSpawnStore
from reconstruction.mob_spawn_export import build_candidates
from reconstruction.branches import build_merged
from reconstruction.auriga import AurigaRenderer
from reconstruction.emulator_profiles import profile as generation_profile, target as active_emulator
from reconstruction.session_quality import summarize_quality
from reconstruction.dialogue_review import build_review_queue
from reconstruction.cast_review import build_cast_review
from reconstruction.entity_metadata import build_metadata_report
from storage.project import fingerprint
from tools.cli_emulator import add_emulator_argument, apply_emulator
from tools.replay_capture import replay

MAX_LOG_BYTES = 128 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024


def analyze(path, definitions):
    started = perf_counter()
    path = Path(path).resolve()
    source_hash = fingerprint(path, MAX_LOG_BYTES)
    profile_hash = fingerprint(generation_profile('dialogue.json'), 2 * 1024 * 1024)
    status_hash = fingerprint(generation_profile('status_ids.json'), 2 * 1024 * 1024)
    job_hash = fingerprint(JOB_IDS_PATH,65536)
    command_policy_hash = fingerprint(generation_profile('script_commands.json'),65536)
    metadata_hash = fingerprint(generation_profile('entity_metadata.json'), 65536)
    world, players = WorldStore(), PlayerStore()
    spawns = MobSpawnStore(world)
    dialogues = DialogueStore(world=world)
    shops = ShopStore(world, dialogues=dialogues)
    barters = BarterStore(world, dialogues=dialogues)
    combat, skills = CombatStore(world), SkillStore(world)
    count = 0
    def consume(event):
        nonlocal count
        world.apply(event, packet_index=count)
        spawns.apply(event, packet_index=count)
        shops.apply(event, packet_index=count)
        barters.apply(event, packet_index=count)
        combat.apply(event, packet_index=count)
        skills.apply(event, packet_index=count)
        values = players.apply(event, packet_index=count)
        dialogues.apply(event, packet_index=count, player_observation=values)
        count += 1
    replay_started = perf_counter()
    transport = replay(path, definitions, on_packet=consume)
    replay_seconds = perf_counter() - replay_started
    if fingerprint(path, MAX_LOG_BYTES) != source_hash:
        raise ValueError('解析中に生ログが変更されました。取得停止後に再実行してください。')
    source_ref = str(path)
    # Same touch_warp_inferences GUI merge/bundle use, so trial selection stays consistent.
    merged = build_merged(((source_ref, item) for item in dialogues.sessions),
                          touch_inferences=list(dialogues.touch_warp_inferences))
    from reconstruction.identity_protection import identity_from_store
    generated = AurigaRenderer(identity=identity_from_store(players)).render_groups(merged['groups'])
    if fingerprint(generation_profile('dialogue.json'), 2 * 1024 * 1024) != profile_hash:
        raise ValueError('解析中に会話生成書式が変更されました。再実行してください。')
    sections = dict(world=world.snapshot(), player=players.snapshot(), dialogues=dialogues.snapshot(source_ref),
                    shops=shops.snapshot(), barters=barters.snapshot(), combat=combat.snapshot(),
                    skills=skills.snapshot(), mob_spawns=spawns.snapshot())
    definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
    report = dict(schema_version=1, emulator=active_emulator(), source_log=source_ref,
                source_sha256=source_hash,
                definitions_sha256=hashlib.sha256(definition_text.encode('utf-8')).hexdigest(),
                dialogue_profile=dict(path=str(generation_profile('dialogue.json')), sha256=profile_hash),
                replay=transport, **sections,
                mob_spawn_candidates=build_candidates(sections['mob_spawns'], {0: source_ref}),
                merged_dialogues=dict(merged, **generated),
                measurements=dict(packet_count=count, replay_seconds=replay_seconds,
                                  total_seconds=perf_counter() - started),
                transport_quality='not_verified')
    report['quality'] = summarize_quality(report)
    report['dialogue_review'] = build_review_queue(sections['dialogues']['conversations'], merged)
    report['skill_cast_review'] = build_cast_review(sections['skills']['observations'])
    report['entity_metadata'] = build_metadata_report(sections['world']['entities'])
    if fingerprint(generation_profile('entity_metadata.json'), 65536) != metadata_hash:
        raise ValueError('解析中に個体メタデータ書式が変更されました。再実行してください。')
    if fingerprint(generation_profile('status_ids.json'), 2 * 1024 * 1024) != status_hash:
        raise ValueError('解析中に状態異常ID変換表が変更されました。再実行してください。')
    if fingerprint(generation_profile('script_commands.json'),65536) != command_policy_hash:
        raise ValueError('解析中に命令判定設定が変更されました。再実行してください。')
    report['script_command_policy'] = dict(path=str(generation_profile('script_commands.json')), sha256=command_policy_hash)
    command_style = AurigaRenderer().templates
    if fingerprint(JOB_IDS_PATH,65536)!=job_hash:
        raise ValueError('解析中に職業class表が変更されました。再実行してください。')
    report['player_class_map'] = dict(path=str(JOB_IDS_PATH),sha256=job_hash)
    report['npc_display_candidates'] = [dict(row,auriga=render_display(dict(name=row['npc_name'],map_name=row['map_name']),
        row['display'] if row['packet_id']!=0x1b0 else {'class_id':row['display']['class_id']},command_style,outside=not row['in_sight']))
        for row in sections['world']['display_observations'] if row['kind']=='NPC' and 'class_id' in row['changes']]
    report['script_command_candidates'] = [dict(row, auriga=render_command(row['fields'], command_style))
                                           for row in sections['dialogues']['script_command_observations']]
    report['status_id_map'] = dict(path=str(generation_profile('status_ids.json')), sha256=status_hash)
    report['entity_metadata_profile'] = dict(path=str(generation_profile('entity_metadata.json')), sha256=metadata_hash)
    report['measurements']['total_seconds'] = perf_counter() - started
    return report


def save_report(path, report, protected=()):
    destination = Path(path).resolve()
    config_root = Path(__file__).resolve().parents[1] / 'config'
    protected = {Path(item).resolve() for item in (*protected, report['source_log'])}
    if destination in protected or destination.is_relative_to(config_root):
        raise ValueError('元ログ・定義・設定へ上書きできません。')
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if len(text.encode('utf-8')) > MAX_REPORT_BYTES:
        raise ValueError('総合解析JSONは64MiB以内にしてください。')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=destination.parent, delete=False, suffix='.tmp') as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', required=True, type=Path)
    cli.add_argument('--output', required=True, type=Path)
    add_emulator_argument(cli)
    args = cli.parse_args()
    try:
        apply_emulator(args.emulator)
        report = analyze(args.log, load_lengths(args.definitions))
        save_report(args.output, report, (args.definitions,))
    except (OSError, ValueError) as exc:
        cli.error(str(exc))
    print(f'Packets {report["measurements"]["packet_count"]}; '
          f'conversations {len(report["dialogues"]["conversations"])}; '
          f'groups {len(report["merged_dialogues"]["groups"])} -> {args.output}')
    print(f'Emulator {report["emulator"]}; quality {report["quality"]["status"]}; '
          f'completeness not_verified; findings {len(report["quality"]["findings"])}')


if __name__ == '__main__':
    main()
