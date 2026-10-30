"""Display-only exclusions, independent of packet decoding and reconstruction."""
import json
import re
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from reconstruction.combat import decode_attack
from reconstruction.skills import decode_skill
from reconstruction.dialogue import decode_dialogue, PRESENTATION_ACTOR_OFFSETS
from reconstruction.decoder import ObservationError

DEFAULT_PATH = Path(__file__).resolve().parent.parent / 'config' / 'ignorepacket.json'


def packet_ids(text):
    tokens = [value for value in re.split(r'[\s,;]+', text.strip()) if value]
    if len(tokens) > 65536 or any(not re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]{1,4}', value) for value in tokens):
        raise ValueError('PacketIDは0000〜FFFFの16進数を空白・改行・カンマで区切ってください。')
    return frozenset(int(value, 16) for value in tokens)


@dataclass(frozen=True)
class IgnorePacket:
    ids: frozenset = frozenset()
    mob_combat: bool = False
    npc_actors: frozenset = frozenset()
    npc_names: frozenset = frozenset()

    def hides(self, event, tags):
        return (tags.get('npc_waitingroom', False) or event.packet_id in self.ids or self.mob_combat and tags.get('mob_combat', False)
                or tags.get('npc_presentation', False) and (
                    tags.get('actor_id') in self.npc_actors or tags.get('npc_name') in self.npc_names))

    def document(self):
        return dict(version=1, packet_ids=[f'{value:04X}' for value in sorted(self.ids)],
                    mob_combat=self.mob_combat, npc_actor_ids=sorted(self.npc_actors),
                    npc_names=sorted(self.npc_names))

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        path = Path(path)
        if path.stat().st_size > 65536:
            raise ValueError('ignorepacket設定は64 KiB以下にしてください。')
        doc = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(doc, dict) or set(doc) != {'version', 'packet_ids', 'mob_combat', 'npc_actor_ids', 'npc_names'}
                or type(doc['version']) is not int or doc['version'] != 1 or type(doc['mob_combat']) is not bool
                or not isinstance(doc['packet_ids'], list) or not all(isinstance(v, str) for v in doc['packet_ids'])
                or not isinstance(doc['npc_actor_ids'], list) or len(doc['npc_actor_ids']) > 1000
                or not all(type(v) is int and 0 <= v <= 0xffffffff for v in doc['npc_actor_ids'])
                or not isinstance(doc['npc_names'], list) or len(doc['npc_names']) > 1000
                or not all(isinstance(v, str) and 0 < len(v) <= 256 for v in doc['npc_names'])):
            raise ValueError('ignorepacket設定の形式が不正です。')
        return cls(packet_ids(' '.join(doc['packet_ids'])), doc['mob_combat'],
                   frozenset(doc['npc_actor_ids']), frozenset(doc['npc_names']))

    def save(self, path=DEFAULT_PATH):
        path = Path(path)
        text = json.dumps(self.document(), ensure_ascii=False, indent=2) + '\n'
        if len(text.encode('utf-8')) > 65536:
            raise ValueError('ignorepacket設定は64 KiB以下にしてください。')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                             dir=path.parent, prefix=path.name + '.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def observation_tags(event, world, session):
    """Resolve identity at observation time, never against a later map/actor reuse."""
    if event.direction != 'RECV':
        return {}
    try:
        if event.packet_id == 0xd7:
            from reconstruction.decoder import Reader
            actor = Reader(event.raw).number(4, 'I')
            entity = world.find_current(event, session, actor, kind='NPC')
            if entity and 18 <= len(event.raw) <= 78 and Reader(event.raw).number(2,'H') == len(event.raw) and any(room['evidence']['packet_id'] == 0xd7 and room['chat_id'] == Reader(event.raw).number(8, 'I')
                              for room in entity.waitingrooms):
                return dict(npc_waitingroom=True, actor_id=actor)
        attack = decode_attack(event)
        skill = decode_skill(event)
        if attack or skill:
            actor = attack['actor_id'] if attack else skill[1]
            return {'mob_combat': world.find_current(event, session, actor, kind='MOB') is not None}
        if event.packet_id in PRESENTATION_ACTOR_OFFSETS:
            _, actor, _ = decode_dialogue(event)
            entity = world.find_current(event, session, actor)
            # Explicit actor IDs remain useful even when appearance was missed.
            return dict(npc_presentation=entity is None or entity.kind == 'NPC',
                        actor_id=actor, npc_name=entity.name if entity and entity.kind == 'NPC' else '')
    except ObservationError:
        pass
    return {}
