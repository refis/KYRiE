"""Scoped conversation actions with packet evidence and explicit status-ID maps."""
from reconstruction.render_inputs import read_render_json,render_profile_size
import json
import math
import re
from pathlib import Path
from reconstruction.decoder import Reader, ObservationError

STATUS_MAP = Path(__file__).resolve().parents[1] / 'config' / 'auriga' / 'status_ids.json'
STATUS_IDS = (0x43f, 0x983, 0x196)


def load_status_ids(path=None, target=None):
    from reconstruction.emulator_profiles import profile, target as active_target, target_for_path
    if path is None:
        target = target or active_target()
        path = profile('status_ids.json', target)
    else:
        path = Path(path)
        target = target or target_for_path(path) or active_target()
    if render_profile_size(path) > 2 * 1024 * 1024:
        raise ValueError('Status ID table exceeds 2MiB')
    data = read_render_json(path)
    if data.get('schema_version') != 1 or data.get('target') != target or data.get('id_namespace') != 'client_status_icon':
        raise ValueError('Status ID table target or namespace mismatch')
    entries = data.get('entries')
    if not isinstance(entries, dict):
        raise ValueError('Invalid status ID entries')
    for key, row in entries.items():
        if (not re.fullmatch(r'0|[1-9][0-9]{0,4}', key) or int(key) > 65535
                or not isinstance(row, dict) or not re.fullmatch(r'SC_[A-Z0-9_]+', row.get('symbol', ''))
                or type(row.get('script_id')) is not int or not 0 <= row['script_id'] <= 65535
                or row.get('argument_policy') not in ('val1_only', 'review')):
            raise ValueError('Invalid status ID mapping')
    return entries


def status_event(packet):
    if packet.direction != 'RECV' or packet.packet_id not in STATUS_IDS:
        return None
    r = Reader(packet.raw)
    if packet.packet_id == 0x196:
        if len(packet.raw) != 9 or r.number(8,'B') not in (0,1):
            raise ObservationError('Invalid status icon load length or flag')
        return r.number(4,'I'), dict(effect_id=r.number(2,'H'), flag=r.number(8,'B'),
            remaining_ms=9999, value1=0, value2=0, value3=0)
    expected = 29 if packet.packet_id == 0x983 else 25
    if len(packet.raw) != expected:
        raise ObservationError('Invalid status change packet length')
    flag = r.number(8, 'B')
    if flag not in (0, 1):
        raise ObservationError('Unsupported status change flag')
    offset = 17 if packet.packet_id == 0x983 else 13
    fields = dict(effect_id=r.number(2, 'H'), flag=flag, remaining_ms=r.number(9, 'I'),
                  value1=r.number(offset, 'I'), value2=r.number(offset + 4, 'I'), value3=r.number(offset + 8, 'I'))
    if packet.packet_id == 0x983:
        fields['tick'] = r.number(13, 'I')
    return r.number(4, 'I'), fields


def validate_actions(conversation):
    if len(conversation.actions) > 512:
        raise ValueError('Conversation action capacity exceeded')
    for row in conversation.actions:
        anchor = row.get('after_step_index')
        if (row.get('kind') not in ('visibility_action', 'status_action', 'progress_action', 'script_command', 'npc_display_action', 'dialogue_size', 'dialogue_position', 'dialogue_alignment')
                or row.get('capture_session') != conversation.capture_session or row.get('flow_id') != conversation.flow_id
                or row.get('cause_confirmed') is not False or row.get('direction') != 'RECV'
                or type(anchor) is not int or not 0 <= anchor < len(conversation.steps)
                or not math.isfinite(row['timestamp']) or row['timestamp'] < conversation.started
                or type(row.get('packet_index')) is not int
                or row['packet_index'] <= conversation.steps[anchor]['packet_index']):
            raise ValueError('Invalid conversation action scope')

        fields = row.get('fields')
        if not isinstance(fields, dict):
            raise ValueError('Invalid conversation action fields')
        kind = row['kind']
        def uint(value):
            return type(value) is int and 0 <= value <= 0xffffffff
        if kind in ('dialogue_size', 'dialogue_position', 'dialogue_alignment'):
            keys, packets = {
                'dialogue_size': ({'height', 'width'}, (0xba2,)),
                'dialogue_position': ({'x', 'y'}, (0xba3, 0xbb5)),
                'dialogue_alignment': ({'alignment'}, (0xba1,))}[kind]
            valid = (row['packet_id'] in packets and set(fields) == keys
                     and all(uint(value) for value in fields.values())
                     and (kind != 'dialogue_alignment' or fields['alignment'] <= 255))
        elif kind == 'npc_display_action':
            valid=(row['packet_id'] in (0x1b0, 0x9ff, 0x9fe, 0x9fd) and isinstance(fields.get('target'),dict) and isinstance(fields['target'].get('name'),str)
                   and isinstance(fields.get('display'),dict) and uint(fields['display'].get('class_id')) and type(fields.get('outside')) is bool)
        elif kind == 'script_command':
            from reconstruction.script_commands import COMMAND_ARGS
            command = fields.get('command')
            valid = command in COMMAND_ARGS and isinstance(fields.get('arguments'), dict) and set(fields['arguments']) == set(COMMAND_ARGS[command])
        elif kind == 'progress_action':
            valid = row['packet_id'] == 0x2f0 and set(fields) == {'seconds', 'color'} and all(uint(v) for v in fields.values())
        elif kind == 'status_action':
            required = {'effect_id', 'flag', 'remaining_ms', 'value1', 'value2', 'value3'}
            valid = (row['packet_id'] in STATUS_IDS and required <= fields.keys() <= required | {'tick'}
                     and all(uint(value) for value in fields.values())
                     and fields['effect_id'] <= 65535 and fields['flag'] in (0, 1))
        else:
            commands = fields.get('commands')
            target = fields.get('target')
            valid = (row['packet_id'] == 0x229 and isinstance(commands, list) and 1 <= len(commands) <= 2
                     and all(command in ('hideonnpc', 'hideoffnpc', 'cloakonnpc', 'cloakoffnpc') for command in commands)
                     and uint(fields.get('options')) and (fields.get('previous_options') is None or uint(fields['previous_options']))
                     and (target is None or isinstance(target, dict)
                          and all(isinstance(target.get(key), str) and target[key] for key in ('name', 'map_name'))))
        if not valid:
            raise ValueError('Invalid conversation action values')
