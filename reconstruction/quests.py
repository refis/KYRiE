"""Bounded quest notifications; objectives and script causes are not inferred."""
from reconstruction.decoder import Reader, ObservationError

ADD_LENGTHS = {0x2b3: 107, 0x9f9: 143, 0xb0c: 155}
COUNT_LAYOUTS = {0x2b5: (6, 12, 'mob_class_id'), 0x9fa: (6, 12, 'quest_objective_id'),
                 0xafe: (6, 16, 'indexed_objective_id'), 0x8fe: (4, 12, 'mob_class_id')}
QUEST_PACKET_IDS = frozenset((*ADD_LENGTHS, *COUNT_LAYOUTS, 0x2b4, 0x2b7))


def valid_counter_fields(fields):
    if not isinstance(fields, dict) or set(fields) != {'layout', 'objective_kind', 'entry_count', 'entries'}:
        return False
    layout = next((value for pid, value in COUNT_LAYOUTS.items() if fields['layout'] == f'{pid:04X}'), None)
    if layout is None or fields['objective_kind'] != layout[2]:
        return False
    entries = fields['entries']
    if (not isinstance(entries, list) or type(fields['entry_count']) is not int
            or not 0 <= fields['entry_count'] <= 3 or len(entries) != fields['entry_count']):
        return False
    for entry in entries:
        keys = {'quest_id', 'objective_id', 'required_count', 'current_count'}
        if layout[1] == 16:
            keys.add('objective_index')
        if not isinstance(entry, dict) or set(entry) != keys or any(type(value) is not int or
                not 0 <= value <= (65535 if key.endswith('_count') else 0xffffffff) for key, value in entry.items()):
            return False
    return True


def decode_quest(packet):
    if packet.direction != 'RECV':
        return None
    pid, r = packet.packet_id, Reader(packet.raw)
    if pid in COUNT_LAYOUTS:
        header, stride, objective_kind = COUNT_LAYOUTS[pid]
        length = len(packet.raw)
        if (not header <= length <= 65535 or r.number(2, 'H') != length
                or (length - header) % stride):
            raise ObservationError('Quest counter length does not match supported layout')
        count = (length - header) // stride
        if count > 3 or (header == 6 and r.number(4, 'H') != count):
            raise ObservationError('Quest counter entry count does not match supported layout')
        entries = []
        for index in range(count):
            offset = header + index * stride
            row = dict(quest_id=r.number(offset, 'I'), objective_id=r.number(offset + 4, 'I'))
            if stride == 16:
                row['objective_index'] = r.number(offset + 8, 'I')
            row.update(required_count=r.number(offset + stride - 4, 'H'), current_count=r.number(offset + stride - 2, 'H'))
            entries.append(row)
        return 'quest_count', dict(layout=f'{pid:04X}', objective_kind=objective_kind, entry_count=count, entries=entries)
    if pid in ADD_LENGTHS:
        if len(packet.raw) != ADD_LENGTHS[pid]:
            raise ObservationError('Quest addition length does not match supported layout')
        count = r.number(15, 'H')
        if count > 3:
            raise ObservationError('Quest objective count exceeds supported layout')
        return 'quest_add', dict(quest_id=r.number(2, 'I'), state=r.number(6, 'B'),
            start_time=r.number(7, 'I'), deadline=r.number(11, 'I'), objective_count=count,
            objective_payload_hex=packet.raw[17:].hex())
    if pid in (0x2b4, 0x2b7):
        if len(packet.raw) != (6 if pid == 0x2b4 else 7):
            raise ObservationError('Quest notification length does not match supported layout')
        fields = dict(quest_id=r.number(2, 'I'))
        if pid == 0x2b7:
            fields['state'] = r.number(6, 'B')
        return ('quest_delete' if pid == 0x2b4 else 'quest_state'), fields
    return None
