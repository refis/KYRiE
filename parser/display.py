"""Declarative receive presentation. No executable expressions in profiles."""
import codecs
from reconstruction.skill_units import UNIT_FIELDS, load_unit_catalog, unit_labels
from reconstruction.reference_names import REFERENCE_FIELDS, PACKETS, load_reference_names, reference_labels
from reconstruction.instance_names import map_name as base_map_name
import json
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from string import Formatter
from reconstruction.player import PlayerStore, DISPLAY_DEFAULTS
from reconstruction.world import WorldStore
from reconstruction.decoder import decode_world_event, ObservationError
from reconstruction.entity_metadata import render_packet_metadata
from reconstruction.npc_walk import npc_walk_wait_ms
from reconstruction.quests import decode_quest

ACTOR_FIELDS = dict(actor_id=0, actor_type=0, class_id=0, speed=0, options=0,
                    actor_name='', x=0, y=0, destination_x=0, destination_y=0, facing=0,
                    first_seen=False, name_valid=True, map_name='不明', reobserved=False, has_changes=False,
                    actor_kind='', changes_text='', walk_wait_extra=50, walk_wait_ms=0)
QUEST_COUNTER_FIELDS = dict(quest_layout='', quest_objective_kind='', quest_entry_count=0, quest_entries='[]')
SCRIPT_FIELDS = dict(command_text='', command_kind='')
STATUS_CONVERT_FIELDS = dict(status_script_id=0, status_symbol='', status_mapped=False)
DECODERS = {'visual_effect_name':REFERENCE_FIELDS,
            'status_icon_name':dict(REFERENCE_FIELDS, **STATUS_CONVERT_FIELDS),
            'skill_unit': UNIT_FIELDS, 'script_command': SCRIPT_FIELDS, 'actor': ACTOR_FIELDS,
            'player': DISPLAY_DEFAULTS, 'quest_counter': QUEST_COUNTER_FIELDS}

CONFIG_ROOT = Path(__file__).resolve().parent.parent / 'config'
DEFAULT_PROFILE = CONFIG_ROOT / 'auriga' / 'display.json'
DEFAULT_SEND_PROFILE = CONFIG_ROOT / 'send_display.json'
TYPES = {'u8': 'B', 'u16': 'H', 'u32': 'I', 'u64': 'Q',
         'i8': 'b', 'i16': 'h', 'i32': 'i', 'i64': 'q'}
META = {'packet_id', 'length', 'direction', 'source', 'connection', 'time', 'name', 'error'}
FORMATS = {'', 'q', 'd', 'x', 'X', '#x', '#06x', '#08x', '06X', '04X', ',d', '+d'}


class ProfileError(ValueError):
    pass


def _keys(obj, allowed, label):
    if not isinstance(obj, dict) or set(obj) - set(allowed):
        raise ProfileError(f'{label}: invalid object or unknown keys')


def _integer(value, label, minimum=0, maximum=65535):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProfileError(f'{label}: expected integer {minimum}..{maximum}')


def _template(value, names, samples):
    if not isinstance(value, str) or len(value) > 16384:
        raise ProfileError('Template must be a string of at most 16384 characters')
    try:
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None and (name not in names or spec not in FORMATS or conversion):
                raise ProfileError(f'Invalid template placeholder: {name}:{spec}')
        _render(value, samples)
    except (ValueError, KeyError, TypeError) as exc:
        raise ProfileError(f'Invalid template: {exc}') from exc


def _render(template, values):
    result = []
    for literal, name, spec, _ in Formatter().parse(template):
        result.append(literal)
        if name is not None:
            value = values[name]
            if spec == 'q' and values.get('_protect_text_' + name):
                # Expression already includes quotes / getstrcharinfo concatenations.
                result.append(str(value))
            else:
                result.append(json.dumps(str(value), ensure_ascii=False) if spec == 'q' else format(value, spec))
    return ''.join(result)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


@dataclass(frozen=True)
class DisplayResult:
    name: str
    text: str
    status: str
    fields: dict = field(default_factory=dict)
    error: str = ''


class DisplayProfile:
    def __init__(self, document):
        _keys(document, {'version', 'encoding', 'defaults', 'fallback', 'error', 'timestamp', 'packets', 'entity_metadata',
                         'instance_warp', 'instance_entry_warp', 'instance_map_reference', 'actor_change_template', 'actor_change_labels',
                         'walk_npc_speed_template', 'walk_npc_wait_template'}, 'profile')
        self.actor_change_template = document.get('actor_change_template')
        self.actor_change_labels = document.get('actor_change_labels',{})
        self.walk_npc_speed_template = document.get('walk_npc_speed_template')
        self.walk_npc_wait_template = document.get('walk_npc_wait_template')
        if (not isinstance(self.actor_change_labels,dict) or len(self.actor_change_labels)>64
                or any(not isinstance(key,str) or not isinstance(value,str) or len(value)>80 for key,value in self.actor_change_labels.items())):
            raise ProfileError('Invalid actor change labels')
        if self.actor_change_template is not None:
            _template(self.actor_change_template,set(ACTOR_FIELDS),dict(ACTOR_FIELDS))
        if self.walk_npc_speed_template is not None:
            _template(self.walk_npc_speed_template, set(ACTOR_FIELDS), dict(ACTOR_FIELDS))
        if self.walk_npc_wait_template is not None:
            _template(self.walk_npc_wait_template, set(ACTOR_FIELDS), dict(ACTOR_FIELDS))
        instance_keys = ('instance_warp', 'instance_entry_warp', 'instance_map_reference')
        for key in instance_keys:
            setattr(self, key, document.get(key))
        if any(key in document for key in instance_keys):
            for key in instance_keys:
                _template(document.get(key), {'map', 'map_reference', 'x', 'y'},
                          dict(map='1@map', map_reference='getmdmapname("1@map")', x=1, y=2))
        self.entity_metadata = document.get('entity_metadata', False)
        if type(self.entity_metadata) is not bool:
            raise ProfileError('entity_metadata must be boolean')
        if type(document.get('version')) is not int or document['version'] != 1:
            raise ProfileError('Unsupported profile version')
        self.encoding = document.get('encoding', 'cp932')
        try:
            if not codecs.lookup(self.encoding)._is_text_encoding:
                raise LookupError('Not a text codec')
        except (LookupError, TypeError) as exc:
            raise ProfileError('Unknown text encoding') from exc
        self.defaults = document.get('defaults', {})
        if not isinstance(self.defaults, dict):
            raise ProfileError('defaults must be an object')
        for key, value in self.defaults.items():
            if not re.fullmatch(r'ctx_[A-Za-z][A-Za-z0-9_]*', key) or type(value) not in (str, int, bool):
                raise ProfileError('State defaults need ctx_ names and scalar values')
        samples = dict(packet_id=1, length=2, direction='RECV', source='NPCAP',
                       connection='test', time='00:00:00.000', name='test', error='test', **self.defaults)
        self.fallback = document['fallback']
        self.error_template = document['error']
        self.timestamp = document['timestamp']
        for template in (self.fallback, self.error_template, self.timestamp):
            _template(template, set(samples), samples)
        self.rules = {}
        packets = document.get('packets')
        if not isinstance(packets, list) or len(packets) > 65536:
            raise ProfileError('packets must be a bounded list')
        for rule in packets:
            self._validate_rule(rule, samples)
            for pid in rule['ids']:
                if not isinstance(pid, str) or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,4}', pid):
                    raise ProfileError('IDs must be hexadecimal strings')
                number = int(pid, 16)
                if number in self.rules:
                    raise ProfileError(f'Duplicate display ID: {pid}')
                self.rules[number] = rule
        self.unit_catalog = (load_unit_catalog() if any(rule.get('decoder') == 'skill_unit'
                             for rule in self.rules.values()) else None)
        self.reference_names = (load_reference_names() if any(rule.get('decoder') in
            ('visual_effect_name','status_icon_name') for rule in self.rules.values()) else None)
        self.status_ids = None

    @classmethod
    def load(cls, path=DEFAULT_PROFILE):
        path = Path(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ProfileError('Display profile exceeds 2 MiB')
        try:
            profile = cls(json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object))
        except (KeyError, TypeError) as exc:
            raise ProfileError(f'Missing or invalid profile field: {exc}') from exc
        if any(rule.get('decoder') == 'status_icon_name' for rule in profile.rules.values()):
            from reconstruction.emulator_profiles import target_for_path
            from reconstruction.conversation_actions import load_status_ids
            target = target_for_path(path)
            if target is not None:
                try:
                    profile.status_ids = load_status_ids(target=target)
                except (OSError, ValueError):
                    profile.status_ids = None
        return profile

    def _validate_rule(self, rule, samples):
        _keys(rule, {'ids', 'name', 'fields', 'template', 'variants', 'remember', 'min_length', 'decoder'}, 'packet')
        if 'decoder' in rule and (not isinstance(rule['decoder'], str) or rule['decoder'] not in DECODERS):
            raise ProfileError('Unknown observation decoder')
        if not isinstance(rule.get('ids'), list) or not rule['ids']:
            raise ProfileError('Packet ids must be a nonempty list')
        if not isinstance(rule.get('name'), str) or not rule['name']:
            raise ProfileError('Packet name is required')
        _integer(rule.get('min_length', 2), 'min_length', 2)
        fields = rule.get('fields', {})
        if not isinstance(fields, dict) or len(fields) > 256:
            raise ProfileError('fields must be a bounded object')
        values = dict(samples, **DECODERS.get(rule.get('decoder'), {}))
        for name, spec in fields.items():
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) or name in values or name.startswith('ctx_'):
                raise ProfileError(f'Invalid or reserved field name: {name}')
            _keys(spec, {'offset', 'type', 'length', 'encoding', 'scale', 'add', 'mask', 'index'}, name)
            _integer(spec.get('offset'), name + '.offset')
            kind = spec.get('type')
            if kind not in (*TYPES, 'string', 'bytes'):
                raise ProfileError(f'Unknown field type: {kind}')
            if 'index' in spec:
                from parser.packet_overlay import INDEX_TAGS
                if not isinstance(spec['index'], str) or spec['index'] not in INDEX_TAGS:
                    raise ProfileError(f'Unknown field index tag: {spec.get("index")}')
            if kind in ('string', 'bytes'):
                if 'length' in spec:
                    _integer(spec['length'], name + '.length')
                if set(spec) & {'scale', 'add', 'mask'}:
                    raise ProfileError('Numeric transforms require an integer field')
                if kind == 'string':
                    try:
                        if not codecs.lookup(spec.get('encoding', self.encoding))._is_text_encoding:
                            raise LookupError('Not a text codec')
                    except (LookupError, TypeError) as exc:
                        raise ProfileError('Unknown field encoding') from exc
                values[name] = 'text'
            else:
                if 'length' in spec or 'encoding' in spec:
                    raise ProfileError('Integer fields cannot specify length/encoding')
                for option in ('scale', 'add', 'mask'):
                    if option in spec:
                        _integer(spec[option], name + '.' + option, -2**64, 2**64)
                values[name] = 1
        _template(rule.get('template'), set(values), values)
        variants = rule.get('variants', [])
        if not isinstance(variants, list) or len(variants) > 256:
            raise ProfileError('variants must be a bounded list')
        for variant in variants:
            _keys(variant, {'when', 'template'}, 'variant')
            when = variant.get('when')
            if not isinstance(when, dict) or not when or set(when) - set(values):
                raise ProfileError('Variant conditions require known fields')
            if any(type(v) not in (int, str, bool) for v in when.values()):
                raise ProfileError('Variant comparisons require scalar values')
            _template(variant.get('template'), set(values), values)
        remember = rule.get('remember', {})
        if not isinstance(remember, dict):
            raise ProfileError('remember must be an object')
        for key, source in remember.items():
            if key not in self.defaults or not isinstance(source, str) or source not in fields:
                raise ProfileError('remember requires a declared state and decoded field')
            if type(values[source]) is not type(self.defaults[key]):
                raise ProfileError('remember field and default types must match')


class ReceiveDisplay:
    def __init__(self, profile, direction='RECV', client_names=None, skill_names=None):
        self.profile = profile
        if direction not in ('RECV', 'SEND'):
            raise ValueError('Unsupported display direction')
        self.direction = direction
        self.states = {}
        self.players = PlayerStore()
        self.world = WorldStore()
        self.client_names = client_names
        self.skill_names = skill_names
        self.command_store = None
        self.command_records = []
        self.command_error = None
        self.command_index = 0
        if any(rule.get('decoder') == 'script_command' for rule in self.profile.rules.values()):
            from reconstruction.script_commands import ScriptCommandStore
            self.command_store = ScriptCommandStore()
        self._needs_index = any(
            isinstance(spec, dict) and spec.get('index')
            for rule in self.profile.rules.values()
            for spec in rule.get('fields', {}).values())
        if self._needs_index and profile.reference_names is None:
            if any(isinstance(spec, dict) and spec.get('index') in ('status_icon', 'visual_effect')
                   for rule in profile.rules.values()
                   for spec in rule.get('fields', {}).values()):
                from reconstruction.reference_names import load_reference_names
                profile.reference_names = load_reference_names()

    def _annotate_indexes(self, rule, fields, event):
        if not getattr(self, '_needs_index', False):
            return
        from parser.packet_overlay import resolve_index_label
        for name, spec in rule.get('fields', {}).items():
            tag = spec.get('index') if isinstance(spec, dict) else None
            if not tag or name not in fields:
                continue
            label = resolve_index_label(
                tag, fields[name],
                world=self.world, capture_session=0,
                connection=event.connection, flow_id=event.flow_id or event.connection,
                client_names=self.client_names, reference_names=self.profile.reference_names,
                skill_names=self.skill_names)
            fields[name + '_index'] = label

    def _changes_text(self, changes):
        parts=[]
        for name,pair in changes.items():
            if name=='appearance_data':
                before,after=pair['before'] or {},pair['after'] or {}
                for key in sorted(set(before)|set(after)):
                    if before.get(key)!=after.get(key):
                        parts.append(f"{self.profile.actor_change_labels.get(key,key)}: {before.get(key)} → {after.get(key)}")
            else:
                parts.append(f"{self.profile.actor_change_labels.get(name,name)}: {json.dumps(pair['before'],ensure_ascii=False) if isinstance(pair['before'],str) else pair['before']} → {json.dumps(pair['after'],ensure_ascii=False) if isinstance(pair['after'],str) else pair['after']}")
        return '; '.join(parts)

    def reset(self):
        self.states.clear()
        self.players = PlayerStore()
        self.world = WorldStore()
        self.command_store = None
        self.command_records = []
        self.command_error = None
        self.command_index = 0
        if any(rule.get('decoder') == 'script_command' for rule in self.profile.rules.values()):
            from reconstruction.script_commands import ScriptCommandStore
            self.command_store = ScriptCommandStore()

    def observe(self, event):
        update = self.players.apply(event)
        self.world.apply(event)
        self.command_records = []
        self.command_error = None
        if self.command_store is not None:
            try:
                self.command_records = self.command_store.observe(event, 0, self.command_index, self.world, None, update)
            except ObservationError as exc:
                self.command_error = str(exc)
            self.command_index += 1
        return update

    def decode(self, event, timestamp=False):
        if event.direction != self.direction:
            return DisplayResult('', '', 'skipped')
        profile = self.profile
        previous = self.players.states.get((0, event.flow_id or event.connection))
        source_map = previous.map_name if previous else None
        update = self.observe(event)
        state = self.states.get(event.connection, profile.defaults)
        values = dict(state, packet_id=event.packet_id, length=len(event.raw),
                      direction=event.direction, source=event.source, connection=event.connection,
                      time=datetime.fromtimestamp(event.timestamp).strftime('%H:%M:%S.%f')[:-3],
                      name='', error='')
        rule = profile.rules.get(event.packet_id)
        prefix = _render(profile.timestamp, values) if timestamp else ''
        try:
            metadata, metadata_fields = render_packet_metadata(event, self.world) if profile.entity_metadata else ('', {})
        except (ValueError, OSError) as exc:
            values['name'], values['error'] = 'Entity metadata', str(exc)
            return DisplayResult('Entity metadata', prefix + _render(profile.error_template, values), 'error', error=str(exc))
        if rule is None:
            if metadata:
                return DisplayResult('Entity group/title', prefix + metadata, 'decoded', metadata_fields)
            return DisplayResult('', prefix + _render(profile.fallback, values), 'unmapped')
        values['name'] = rule['name']
        fields = {}
        try:
            if len(event.raw) < rule.get('min_length', 2):
                raise ValueError('Packet is shorter than display min_length')
            decoder = rule.get('decoder')
            if decoder == 'script_command':
                if self.command_error:
                    raise ValueError(self.command_error)
                from reconstruction.auriga import AurigaRenderer
                from reconstruction.script_commands import render_command
                derived = dict(SCRIPT_FIELDS)
                if self.command_records:
                    derived['command_text'] = '\n'.join(render_command(row['fields'], AurigaRenderer().templates) for row in self.command_records)
                    derived['command_kind'] = self.command_records[-1]['fields']['command']
                if not derived['command_text']:
                    return DisplayResult(rule['name'], '', 'decoded', derived)
                values.update(derived)
                fields.update(derived)
            elif decoder == 'player':
                if update is None:
                    update = dict(DISPLAY_DEFAULTS, event_kind='unresolved')
                if update.get('observation_error'):
                    raise ValueError(update['observation_error'])
                values.update(update)
                fields.update(update)
            elif decoder == 'quest_counter':
                quest = decode_quest(event)
                if quest is None or quest[0] != 'quest_count':
                    raise ValueError('Not a supported quest counter packet')
                decoded = quest[1]
                derived = dict(quest_layout=decoded['layout'], quest_objective_kind=decoded['objective_kind'],
                    quest_entry_count=decoded['entry_count'], quest_entries=json.dumps(decoded['entries'], ensure_ascii=False))
                values.update(derived)
                fields.update(derived)
            elif decoder == 'actor':
                observation = decode_world_event(event)
                if observation is None or observation.kind != 'actor_seen':
                    raise ValueError('Not an actor appearance packet')
                derived = dict(ACTOR_FIELDS, actor_id=observation.actor_id)
                derived['name_valid'] = not bool(observation.field_issues)
                derived.update({key: value for key, value in observation.fields.items() if value is not None})
                derived['actor_name'] = observation.fields.get('name', '')
                derived['facing'] = observation.fields.get('direction', 0)
                scene = self.world.scenes.get((0, event.connection))
                identity = (0, event.connection, scene.generation if scene else 0, observation.actor_id)
                entity = self.world.entities.get(self.world.current.get(identity))
                record=self.world.last_actor_observation
                derived['first_seen'] = bool(record and record['first_observation'])
                derived.update(reobserved=bool(record and not record['first_observation']),has_changes=bool(record and record['changes']),actor_kind=entity.kind if entity else '')
                if record:
                    derived['changes_text'] = self._changes_text(record['changes'])
                player = self.players.states.get((0, event.flow_id or event.connection))
                derived['map_name'] = player.map_name if player and player.map_name else '不明'
                values.update({key: derived[key] for key in ACTOR_FIELDS})
                fields.update({key: derived[key] for key in ACTOR_FIELDS})
            for name, spec in rule.get('fields', {}).items():
                start, kind = spec['offset'], spec['type']
                length = struct.calcsize('<' + TYPES[kind]) if kind in TYPES else spec.get('length', len(event.raw) - start)
                if length < 0 or start + length > len(event.raw):
                    raise ValueError(f'{name}: field exceeds packet bounds')
                data = event.raw[start:start + length]
                if kind in TYPES:
                    value = struct.unpack('<' + TYPES[kind], data)[0]
                    if 'mask' in spec:
                        value &= spec['mask']
                    value = value * spec.get('scale', 1) + spec.get('add', 0)
                elif kind == 'bytes':
                    value = data.hex(' ')
                else:
                    value = data.split(b'\0', 1)[0].decode(spec.get('encoding', profile.encoding), errors='strict')
                fields[name] = value
                values[name] = value
            self._annotate_indexes(rule, fields, event)
            if decoder == 'skill_unit':
                if event.packet_id != 0x9ca or len(event.raw) != 23 or struct.unpack_from('<H',event.raw,2)[0] != 23:
                    raise ValueError('Unsupported skill unit packet layout')
                unit_type = struct.unpack_from('<I',event.raw,16)[0]
                derived = unit_labels(profile.unit_catalog,unit_type)
                fields.update(derived)
                values.update(derived)
            if decoder in ('visual_effect_name','status_icon_name'):
                namespace = 'visual_effect' if decoder == 'visual_effect_name' else 'status_icon'
                expected = PACKETS[namespace].get(event.packet_id)
                if event.direction != 'RECV' or expected is None or len(event.raw) != expected:
                    raise ValueError('Unsupported reference-name packet layout')
                offset, number_type = (6, '<I') if namespace == 'visual_effect' else (2, '<H')
                number = struct.unpack_from(number_type,event.raw,offset)[0]
                derived = reference_labels(profile.reference_names,namespace,number)
                if decoder == 'status_icon_name':
                    entry = (profile.status_ids or {}).get(str(number))
                    if entry:
                        derived.update(status_script_id=entry['script_id'], status_symbol=entry['symbol'],
                                       status_mapped=True)
                    else:
                        derived.update(status_script_id=0, status_symbol='', status_mapped=False)
                fields.update(derived)
                values.update(derived)
            template = rule['template']
            for variant in rule.get('variants', []):
                if all(values[key] == expected for key, expected in variant['when'].items()):
                    template = variant['template']
                    break
            if profile.instance_warp is not None and event.packet_id in (0x91, 0x92) and '@' in fields.get('map', ''):
                values['map'] = base_map_name(fields['map'])
                if source_map and '@' in source_map:
                    values['map_reference'] = _render(profile.instance_map_reference, values)
                    template = profile.instance_warp
                else:
                    template = profile.instance_entry_warp
            record = self.world.last_actor_observation
            # Known walk NPCs (type 12): npcwalkto on 0x9FD; setnpcspeed on every 0x9FE/0x9FF (MARiA).
            walk_npc_move = (decoder == 'actor' and event.packet_id == 0x9fd
                             and values.get('actor_type') == 12 and values.get('reobserved'))
            walk_npc_speed = (decoder == 'actor' and event.packet_id in (0x9fe, 0x9ff)
                              and values.get('actor_type') == 12)
            if decoder == 'actor' and values.get('reobserved') and not walk_npc_move:
                if not values['has_changes'] and values.get('name_valid', True) and not walk_npc_speed:
                    return DisplayResult(rule['name'], '', 'decoded', fields)
                if values['has_changes'] and profile.actor_change_template is not None:
                    template = profile.actor_change_template
                elif walk_npc_speed and not values['has_changes'] and profile.walk_npc_speed_template:
                    template = profile.walk_npc_speed_template
            if walk_npc_move:
                values['walk_wait_extra'] = 50
                try:
                    values['walk_wait_ms'] = npc_walk_wait_ms(
                        values['x'], values['y'], values['destination_x'], values['destination_y'],
                        values['speed'], extra_ms=values['walk_wait_extra'])
                except ValueError:
                    values['walk_wait_ms'] = 0
                fields['walk_wait_extra'] = values['walk_wait_extra']
                fields['walk_wait_ms'] = values['walk_wait_ms']
            from reconstruction.identity_protection import apply_to_display_values, identity_from_player
            player_state = self.players.states.get((0, event.flow_id or event.connection))
            identity = identity_from_player(player_state)
            render_values = apply_to_display_values(values, identity)
            text = prefix + _render(template, render_values)
            if (walk_npc_speed and profile.walk_npc_speed_template
                    and values.get('has_changes') and 'setnpcspeed' not in text):
                text += '\n' + _render(profile.walk_npc_speed_template, render_values)
            # After npcwalkto, pause for walk duration so later script/timers resume (sleep/sleep2 stack).
            if (walk_npc_move and profile.walk_npc_wait_template and 'npcwalkto' in text
                    and values.get('walk_wait_ms', 0) > 0):
                text += '\n' + _render(profile.walk_npc_wait_template, render_values)
            if record and event.packet_id in (0x9ff,0x9fe,0x9fd,0x1b0):
                if event.packet_id==0x1b0 and not record['changes']:
                    return DisplayResult(rule['name'],'','decoded',fields)
                if event.packet_id==0x1b0 and profile.actor_change_template is not None:
                    change_values = apply_to_display_values(
                        dict(values, actor_kind=record['kind'], actor_id=record['actor_id'],
                             changes_text=self._changes_text(record['changes'])), identity)
                    text = prefix + _render(profile.actor_change_template, change_values)
                if record['kind']=='NPC' and 'class_id' in record['changes']:
                    from reconstruction.actor_appearance import render_display
                    from reconstruction.auriga import AurigaRenderer
                    display=record['display'] if event.packet_id!=0x1b0 else {'class_id':record['display']['class_id']}
                    text += '\n'+render_display(dict(name=record['npc_name'],map_name=record['map_name']),display,AurigaRenderer().templates,outside=not record['in_sight'])

            if metadata:
                text += '\n' + metadata
                fields.update(metadata_fields)
            updates = {key: fields[source] for key, source in rule.get('remember', {}).items()}
            if updates:
                # Bound state history; GUI replays retained events on profile reload.
                if event.connection not in self.states and len(self.states) >= 4096:
                    self.states.pop(next(iter(self.states)))
                self.states[event.connection] = dict(state, **updates)
            return DisplayResult(rule['name'], text, 'decoded', fields)
        except (ValueError, struct.error) as exc:
            values['error'] = str(exc)
            return DisplayResult(rule['name'], prefix + _render(profile.error_template, values),
                                 'error', fields, str(exc))
