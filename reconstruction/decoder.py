"""Bounds-checked MARiA-compatible entity observations, independent of display."""
from dataclasses import dataclass, field
import struct

from events import PacketEvent
from reconstruction.actor_appearance import player_class


class ObservationError(ValueError):
    pass


class TextDecodingError(ObservationError):
    pass


@dataclass(frozen=True)
class WorldEvent:
    kind: str
    packet: PacketEvent
    actor_id: int | None
    fields: dict
    field_issues: dict = field(default_factory=dict)


class Reader:
    def __init__(self, raw):
        self.raw = raw

    def take(self, offset, size):
        if offset < 0 or size < 0 or offset + size > len(self.raw):
            raise ObservationError(f'Field exceeds packet bounds at offset {offset}, size {size}')
        return self.raw[offset:offset + size]

    def number(self, offset, code):
        size = struct.calcsize('<' + code)
        return struct.unpack('<' + code, self.take(offset, size))[0]

    def text(self, offset, size=None):
        data = self.take(offset, len(self.raw) - offset if size is None else size).split(b'\0', 1)[0]
        try:
            return data.decode('cp932', errors='strict')
        except UnicodeError as exc:
            raise TextDecodingError(f'Invalid cp932 field at offset {offset}') from exc

    def position(self, offset, moving=False):
        data = self.take(offset, 6 if moving else 3)
        fields = dict(x=(data[0] << 2) | (data[1] >> 6),
                      y=((data[1] & 0x3f) << 4) | (data[2] >> 4))
        if moving:
            fields.update(destination_x=((data[2] & 0xf) << 6) | (data[3] >> 2),
                          destination_y=((data[3] & 3) << 8) | data[4])
        else:
            fields['direction'] = data[2] & 0xf
        return fields


def incomplete_name_diagnostic(raw, offset):
    """Expose a valid prefix as non-authoritative evidence, never as an entity name."""
    data = raw[offset:]
    if not data or b'\0' in data:
        return None
    try:
        data.decode('cp932', errors='strict')
    except UnicodeDecodeError as exc:
        if exc.start == len(data)-1 and exc.reason == 'incomplete multibyte sequence':
            return dict(reason='incomplete_cp932_tail',truncation_suspected=True,
                        valid_prefix=data[:exc.start].decode('cp932',errors='strict'),
                        raw_hex=data.hex(),name_offset=offset,observed_bytes=len(data),
                        authoritative_name=False)
    return None


def decode_world_event(packet):
    if packet.direction != 'RECV':
        return None
    r = Reader(packet.raw)
    pid = packet.packet_id
    if pid in (0x9fe, 0x9ff, 0x9fd):
        if r.number(2, 'H') != len(packet.raw):
            raise ObservationError('Actor packet total length does not match raw bytes')
        name_offset = {0x9fe: 83, 0x9ff: 84, 0x9fd: 90}[pid]
        r.take(0, name_offset)
        actor_type = r.number(4, 'B')
        if actor_type not in (5, 6, 12):
            return WorldEvent('actor_seen', packet, r.number(5, 'I'), dict(actor_type=actor_type))
        fields = dict(actor_type=actor_type, speed=r.number(13, 'H'),
                      options=r.number(19, 'I'), class_id=r.number(23, 'H'))
        if actor_type in (6,12) and player_class(fields['class_id']):
            moving = pid == 0x9fd
            fields['appearance_data'] = dict(sex=r.number(66 if moving else 62,'B'),
                hair_style=r.number(25,'H'), head_bottom=r.number(35,'H'),
                head_top=r.number(41 if moving else 37,'H'), head_mid=r.number(43 if moving else 39,'H'),
                hair_color=r.number(45 if moving else 41,'H'), cloth_color=r.number(47 if moving else 43,'H'),
                robe=r.number(51 if moving else 47,'H'), style=r.number(88 if moving else 81 if pid==0x9fe else 82,'H'))
        else:
            fields['appearance_data'] = {}
        issues = {}
        try:
            fields['name'] = r.text(name_offset)
        except TextDecodingError as exc:
            issues['name'] = str(exc)
            diagnostic = incomplete_name_diagnostic(packet.raw, name_offset)
            if diagnostic is not None:
                fields['name_diagnostic'] = diagnostic
                issues['name'] += '; incomplete CP932 tail at observed name boundary (truncation suspected)'
        fields.update(r.position(67 if pid == 0x9fd else 63, moving=pid == 0x9fd))
        if pid != 0x9fd:
            fields.update(destination_x=None, destination_y=None)
        return WorldEvent('actor_seen', packet, r.number(5, 'I'), fields, issues)
    if pid == 0xadf:
        r.take(0, 34)
        fields, issues = dict(group_id=r.number(6, 'I')), {}
        for name, offset, size in (('name', 10, 24), ('title', 34, len(packet.raw) - 34)):
            try:
                fields[name] = r.text(offset, size)
            except TextDecodingError as exc:
                issues[name] = str(exc)
        return WorldEvent('actor_name', packet, r.number(2, 'I'), fields, issues)
    if pid == 0x95:
        r.take(0, 30)
        return WorldEvent('actor_name', packet, r.number(2, 'I'), dict(name=r.text(6, 24)))
    if pid == 0x80:
        return WorldEvent('actor_removed', packet, r.number(2, 'I'), dict(reason=r.number(6, 'B')))
    if pid == 0x88:
        return WorldEvent('actor_update', packet, r.number(2, 'I'), dict(x=r.number(6, 'H'), y=r.number(8, 'H'),
                          destination_x=None, destination_y=None))
    if pid == 0x1b0:
        if len(packet.raw)!=11:
            raise ObservationError('Invalid class change packet length')
        return WorldEvent('actor_update', packet, r.number(2, 'I'), dict(class_id=r.number(7, 'I')))
    if pid == 0x229:
        r.take(0, 15)
        return WorldEvent('actor_update', packet, r.number(2, 'I'), dict(options=r.number(10, 'I')))
    if pid == 0x977:
        return WorldEvent('actor_update', packet, r.number(2, 'I'),
                          dict(hp=r.number(6, 'i'), max_hp=r.number(10, 'i')))
    if pid == 0xa36:
        return WorldEvent('actor_update', packet, r.number(2, 'I'), dict(hp_percent=r.number(6, 'B') * 5))
    if pid in (0x91, 0x92):
        r.take(0, 28 if pid == 0x92 else 22)
        return WorldEvent('map_changed', packet, None,
                          dict(map_name=r.text(2, 16), x=r.number(18, 'H'), y=r.number(20, 'H')))
    return None
