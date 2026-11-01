"""External-template Auriga review output. Unknown causes never become conditions."""
from reconstruction.render_inputs import read_render_json
from reconstruction.touch import is_touch, merge_contexts
from reconstruction.conversation_actions import load_status_ids
from reconstruction.script_commands import COMMAND_ARGS, render_command
from reconstruction.actor_appearance import declaration_class, render_display, VISUAL_FIELDS
from reconstruction.instance_names import map_name as base_map_name, npc_name as base_npc_name
import hashlib
import json
import re
from pathlib import Path
from string import Formatter
from reconstruction.branches import conversation_path, validate_resources, validate_external
from reconstruction.timing import build_timeline
from reconstruction.entity_metadata import append_initialization, render_npc_initialization, metadata_values
from reconstruction.menu_loops import fold_menu_loops, share_menu_continuations
from reconstruction.announcements import template_values as announcement_values
from reconstruction.npc_initial_state import visibility_state
from reconstruction.identity_protection import quote_text

DEFAULT_DIALOGUE_PROFILE = Path(__file__).resolve().parent.parent / 'config' / 'auriga' / 'dialogue.json'


def _dialogue_profile(path=None):
    from reconstruction.emulator_profiles import profile, target_for_path, target as active_target
    path = Path(path) if path is not None else profile('dialogue.json')
    return path, target_for_path(path) or active_target()
STYLE_FIELDS = {'indent': set(), 'block_open': set(), 'block_close': set(), 'switch_open': set(),
                'while_open': set(), 'continue': set(), 'loop_review': set(),
                'case': {'value'}, 'break': set(), 'alternatives': set(), 'alternative': {'number'},
                'input_number_observation': {'value'}, 'input_text_observation': {'value'}}
PRESENTATION_FIELDS = {'dialogue_size': {'height', 'width'},
                       'dialogue_position': {'x', 'y'}, 'dialogue_alignment': {'alignment'}, 'emotion': {'value'}, 'effect': {'value'}, 'effect_remove': {'value'}, 'sound': {'sound', 'mode', 'interval'},
                       'effect_value': {'effect_id', 'value'}, 'external_effect_value': {'effect_id', 'value', 'target'},
                       'event_marker': {'x', 'y', 'state', 'kind'},
                       'external_event_marker': {'x', 'y', 'state', 'kind', 'target'},
                       'hat_effect': {'enabled', 'effect_id'},
                       'external_hat_effect': {'enabled', 'effect_id', 'target'},
                       'colored_speech': {'color_hex', 'text'},
                       'external_colored_speech': {'color_hex', 'text', 'target'},
                       'status_enter': {'effect_id', 'remaining_ms', 'value1', 'value2', 'value3', 'tick'},
                       'external_status_enter': {'effect_id', 'remaining_ms', 'value1', 'value2', 'value3', 'tick', 'target'},
                       'mercenary': {'name', 'duration'},
                       'external_mercenary': {'name', 'duration', 'target'},
                       'external_effect_remove': {'value', 'target'},
                       'classchange': {'class_id', 'kind'},
                       'progressbar': {'seconds', 'color'},
                       'viewpoint': {'kind', 'x', 'y', 'marker_id', 'color'},
                       'viewpoint_observation': {'kind', 'x', 'y', 'marker_id', 'color'},
                       'overhead': {'text'},
                       'unittalk': {'text'},
                       'external_candidate': {'evidence'},
                       'external_adoption_review': set(),
                       'external_emotion': {'value', 'target'}, 'external_effect': {'value', 'target'},
                       'external_overhead': {'text', 'target'}, 'external_unittalk': {'text', 'target'},
                       'adopted_external_emotion': {'value', 'target'}, 'adopted_external_effect': {'value', 'target'},
                       'adopted_external_effect_remove': {'value', 'target'},
                       'adopted_external_overhead': {'text', 'target'},
                       'adopted_external_unittalk': {'text', 'target'},
                       'external_sound': {'sound', 'mode', 'interval', 'target'},
                       'announcement': {'text', 'flag'},
                       'announcement_styled': {'text', 'color', 'font_type', 'font_size', 'font_align', 'font_y'},
                       'presentation_warning': {'count'}}
FILE_FIELDS = {'npc_empty': {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id'},
               'touch_label': set(),
               'touch_review': set(), 'touch_provisional': set(),
               'warp_npc': {'map_name', 'x', 'y', 'direction', 'npc_name', 'radius_x', 'radius_y', 'destination', 'destination_x', 'destination_y'},
               'npc_file_header': {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id'},
               'timeout_normalized_warning': {'count'},
               'late_reply_warning': {'count'},
               'timeout_warning': {'prompt_kind'}, 'aborted_wait': {'prompt_kind'},
               'quest_set': {'quest_id'}, 'quest_delete': {'quest_id'}, 'quest_wait_review': set(),
               'npc_file_header_hidden': {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id'},
               'npc_file_header_cloaked': {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id'},
               'npc_initial_state_conflict': set(),
               'npc_shop_ids_review': set(), 'npc_shop_conflict': set(),
               'instance_map_reference': {'name'}, 'instance_npc_reference': {'name'},
               'instance_entry_warp': {'map_name', 'x', 'y'},
               'npc_metadata_only': set(),
               'npc_unobserved_body': set(), 'npc_bundle_header': {'count', 'excluded', 'mode'},
               'npc_name_conflict': {'name'},
               'npc_file_footer': set(), 'shop_boundary': set(), 'callshop': {'shop_name'},
               'barter_boundary': set(), 'callbarter_review': {'shop_name'},
               'close2_observed': set(), 'post_close_warp': {'map_name', 'x', 'y'}}
for _suffix in ('', '_hidden', '_cloaked'):
    FILE_FIELDS['npc_touch_header' + _suffix] = {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id', 'radius_x', 'radius_y'}
    FILE_FIELDS['npc_empty' + _suffix] = {'map_name', 'x', 'y', 'direction', 'npc_name', 'class_id'}
for _command in ('hideonnpc', 'hideoffnpc', 'cloakonnpc', 'cloakoffnpc'):
    FILE_FIELDS[_command] = set()
    FILE_FIELDS[_command + '_target'] = {'target'}
FILE_FIELDS.update({'unittalk_target': {'text', 'target'}, 'progress_action': {'seconds', 'color'},
                    'status_start': {'symbol', 'duration', 'value'}, 'status_end': {'symbol'},
                    'status_review': {'evidence'}, 'action_observation': {'evidence'}, 'action_wait_review': set()})
for _command, _args in COMMAND_ARGS.items():
    FILE_FIELDS['script_' + _command] = set(_args)
FILE_FIELDS['script_review'] = {'code', 'reason'}
FILE_FIELDS['script_rendered'] = {'text'}
FILE_FIELDS.update({'npc_display_class': {'target','class_id'}, 'npc_display_full': {'target','class_id',*VISUAL_FIELDS},
                    'npc_display_unknown': set(), 'npc_display_outside': {'code'}})
FILE_FIELDS['script_drop_lifetime_note'] = {'lifetime_ms','base_ms'}
RESOURCE_FIELDS = {'resource_header': set(),
    'resource_quest_count': {'packet_index', 'layout', 'objective_kind', 'entry_count', 'entries'},
    'resource_quest_add': {'packet_index', 'quest_id', 'state', 'start_time', 'deadline', 'objective_count', 'objective_payload_hex'},
    'resource_quest_delete': {'packet_index', 'quest_id'}, 'resource_quest_state': {'packet_index', 'quest_id', 'state'},
    'resource_trial': {'capture_session', 'conversation_id', 'source_ref'},
    'resource_zeny': {'packet_index', 'value', 'delta'},
    'resource_zeny_unknown': {'packet_index', 'value'},
    'resource_item_gain': {'packet_index', 'item_id', 'amount', 'index'},
    'resource_item_loss': {'packet_index', 'item_id', 'amount', 'index'},
    'resource_map': {'packet_index', 'map_name', 'x', 'y'},
    'resource_adoption_review': set(),
    'zeny_set': {'delta_signed'},
    'map_warp': {'map_name', 'x', 'y'},
    'map_warp_review': {'map_name', 'x', 'y'}}
OPTIONAL_FIELDS = {'observed_gap': {'duration_ms'},
                   'merged_header': {'id', 'npc_name', 'map_name', 'observations'},
                   'merge_conflict': set(), 'merge_boundary': set(), 'merge_input': set(), 'merge_unavailable': set(),
                   **STYLE_FIELDS, **PRESENTATION_FIELDS, **FILE_FIELDS, **RESOURCE_FIELDS}
FIELDS = {'header': {'id', 'actor_id'}, 'mes': {'text'}, 'cutin': {'image', 'position'},
          'menu': {'options'}, 'label': {'label'}, 'goto': {'label'}, **OPTIONAL_FIELDS}
KEYS = (set(FIELDS) - set(OPTIONAL_FIELDS)) | {'partial', 'next', 'clear', 'close', 'close2', 'number', 'text',
                      'unknown', 'pending', 'ambiguous', 'input_observed', 'end'}


def _quote(value):
    return json.dumps(value, ensure_ascii=False)


class AurigaRenderer:
    def __init__(self, path=None, identity=None):
        from reconstruction.emulator_profiles import profile
        path, self._target = _dialogue_profile(path)
        self.identity = dict(identity or {})
        self.status_ids = load_status_ids(profile('status_ids.json', self._target), target=self._target)
        self.templates = read_render_json(path)
        if not isinstance(self.templates, dict):
            raise ValueError('Dialogue profile must be an object')
        missing = (set(STYLE_FIELDS) | set(PRESENTATION_FIELDS) | set(FILE_FIELDS) | set(RESOURCE_FIELDS)) - self.templates.keys()
        if missing:
            defaults = read_render_json(profile('dialogue.json', self._target))
            for key in missing:
                self.templates[key] = defaults.get(key, read_render_json(DEFAULT_DIALOGUE_PROFILE)[key])
        for key in KEYS | (set(OPTIONAL_FIELDS) & self.templates.keys()):
            value = self.templates.get(key)
            if not isinstance(value, str):
                raise ValueError(f'Missing dialogue template: {key}')
            for _, name, spec, conversion in Formatter().parse(value):
                if name is not None and (name not in FIELDS.get(key, set()) or spec or conversion):
                    raise ValueError(f'Invalid dialogue template field: {key}')
        indent = self.templates['indent']
        if not 1 <= len(indent) <= 16 or any(char not in ' \t' for char in indent):
            raise ValueError('Indent must contain 1..16 spaces or tabs')

    def _text(self, value):
        return quote_text(value, self.identity)

    def render(self, conversation, presentation_check=None, shop_call_name=None, *, include_initialization=True, identity=None):
        if identity is not None:
            self.identity = dict(identity)
        validate_resources(conversation)
        validate_external(conversation)
        preamble = [('header', dict(id=conversation.id, actor_id=conversation.actor_id))]
        if conversation.late_replies:
            preamble.append(('late_reply_warning', dict(count=len(conversation.late_replies))))
        preamble.extend(('action_observation', dict(evidence=json.dumps(row, ensure_ascii=True, sort_keys=True))) for row in conversation.actions)
        preamble.extend(self._external_preamble(conversation))
        preamble.extend(self._resource_preamble([dict(conversation_id=conversation.id,
            capture_session=conversation.capture_session, source_ref='',
            observations=conversation.resource_observations)]))
        if presentation_check and presentation_check['conflicts']:
            preamble.append(('presentation_warning', dict(count=presentation_check['conflicts'])))
        if not conversation.observed_open and not is_touch(conversation.npc):
            preamble.append(('partial', {}))
        nodes = [dict(id=0, kind='root', fields={}, children=[])]
        timing = build_timeline(conversation)
        timing_rows = {row['step_index']: row for row in timing['rows'] if row['step_index'] is not None}
        has_content = (bool(conversation.actions) or is_touch(conversation.npc)
                       or conversation.status in ('shop_opened', 'barter_opened') or
                       any(step['kind'] not in ('open', 'dismiss') for step in conversation.steps))
        if not has_content:
            preamble.append(('pending', {}))
        tokens = conversation_path('', conversation, strict=False) if has_content else []
        for token in tokens:
            node_id = len(nodes)
            nodes[-1]['children'].append(node_id)
            node = dict(id=node_id, kind=token['kind'], fields=token['fields'], children=[])
            index = token['evidence']['step_index']
            if index is not None and token['kind'] not in ('end', 'boundary', 'pending'):
                row = timing_rows[index]
                if row['candidate']:
                    node['observed_gap'] = row['delta_ms']
            nodes.append(node)
        body = self._render_nodes(nodes, preamble, shop_call_name=shop_call_name,
                                  map_name=conversation.npc.get('map_name'), npc_name=conversation.npc.get('name'))
        if not include_initialization:
            return body
        from reconstruction.emulator_profiles import profile
        return append_initialization(body, [conversation.npc], profile('entity_metadata.json', self._target))

    ADOPTABLE_EXTERNAL_KINDS = frozenset(('emotion', 'effect', 'effect_remove', 'overhead', 'unittalk'))

    def _external_preamble(self, conversation):
        result = []
        adopted_any = False
        for row in conversation.external_presentations:
            result.append(('external_candidate', dict(evidence=json.dumps(row, ensure_ascii=True, sort_keys=True))))
            name = row['npc'].get('name')
            if not name:
                continue
            target = _quote(base_npc_name(name, row['npc'].get('map_name')))
            if '@' in (row['npc'].get('map_name') or ''):
                target = self.templates['instance_npc_reference'].format(name=target)
            values = dict(row['fields'], target=target)
            if 'text' in values:
                values['text'] = self._text(values['text'])
            if 'sound' in values:
                values['sound'] = _quote(values['sound'])
            kind = row['kind']
            if kind == 'colored_speech':
                values['color_hex'] = f"{values.pop('color'):08X}"
            adopted = row.get('adoption_confirmed') is True and kind in self.ADOPTABLE_EXTERNAL_KINDS
            if kind == 'status_enter' and 'tick' not in values:
                values['tick'] = 'n/a'
            if kind == 'mercenary' and 'name' in values:
                values['name'] = _quote(values['name'])
            if kind not in ('emotion', 'effect', 'effect_remove', 'overhead', 'unittalk',
                            'sound', 'effect_value', 'event_marker', 'hat_effect', 'colored_speech',
                            'status_enter', 'mercenary'):
                continue
            if adopted:
                adopted_any = True
                result.append(('adopted_external_' + kind, values))
            else:
                result.append(('external_' + kind, values))
        if adopted_any:
            result.insert(0, ('external_adoption_review', {}))
        return result

    @staticmethod
    def _resource_preamble(trials):
        result = []
        for trial in trials:
            if not trial['observations']:
                continue
            if not result:
                result.append(('resource_header', {}))
            result.append(('resource_trial', dict(capture_session=trial['capture_session'],
                conversation_id=trial['conversation_id'], source_ref=_quote(trial['source_ref']))))
            for row in trial['observations']:
                fields = dict(row['fields'], packet_index=row['packet_index'])
                if row['kind'] == 'zeny':
                    known = fields.pop('delta_known')
                    if not known:
                        fields.pop('delta')
                    key = 'resource_zeny' if known else 'resource_zeny_unknown'
                else:
                    key = 'resource_' + row['kind']
                    if row['kind'] == 'quest_count':
                        fields['entries'] = json.dumps(fields['entries'], ensure_ascii=True)
                    if row['kind'] == 'map':
                        fields['map_name'] = _quote(fields['map_name'])
                result.append((key, fields))
        return result

    @staticmethod
    def placement_values(npc):
        for key, limit in (('x', 1023), ('y', 1023), ('direction', 7), ('class_id', 65535)):
            if type(npc.get(key)) is not int or not 0 <= npc[key] <= limit:
                raise ValueError('NPC配置の数値が未観測または範囲外です。')
        initial_class = declaration_class(npc)
        if type(initial_class) is not int or not 0 <= initial_class <= 65535:
            raise ValueError('NPC初期配置classが未観測または範囲外です。')
        map_name, name = npc.get('map_name'), npc.get('name')
        if not isinstance(map_name, str) or not re.fullmatch(r'[A-Za-z0-9_@.-]{1,32}', map_name):
            raise ValueError('マップ名が未観測または配置宣言に使用できません。')
        if (not isinstance(name, str) or not name.strip() or '::' in name
                or any(char in ',;{}"/\\' or ord(char) < 32 or ord(char) == 127
                       or (char.isspace() and char != ' ') for char in name)):
            raise ValueError('NPC名が未観測または配置宣言に使用できません。')
        try:
            if len(name.encode('cp932')) > 23:
                raise ValueError('NPC名が候補出力の上限23バイトを超えています。')
        except UnicodeEncodeError as exc:
            raise ValueError('NPC名をcp932で表現できません。') from exc
        return dict(map_name=base_map_name(map_name), npc_name=base_npc_name(name, map_name), x=npc['x'], y=npc['y'],
                    direction=npc['direction'], class_id=initial_class)

    def render_npc_file(self, conversation, group=None, presentation_check=None, shop_call_name=None):
        """Wrap an existing review body; never supply unknown placement values."""
        npc = group['npc'] if group is not None else conversation.npc
        if group is not None and shop_call_name is not None:
            raise ValueError('callshop出力には単一の観測経路を選択してください。')
        if group is not None:
            states = {visibility_state(row['conversation'].get('npc', {})) for row in group['contributions']}
            if len(states - {'unobserved'}) > 1:
                raise ValueError('NPC初回状態が観測間で不一致です。個別候補と根拠を確認してください。')
            observed = next((row['conversation']['npc'] for row in group['contributions']
                             if visibility_state(row['conversation'].get('npc', {})) != 'unobserved'), None)
            if observed:
                npc = dict(npc, initial_options=observed['initial_options'],
                           initial_state_evidence=observed.get('initial_state_evidence', {}))
        if group is not None:
            touches = [row['conversation']['npc']['touch'] for row in group['contributions']
                       if is_touch(row['conversation'].get('npc', {}))]
            if touches:
                npc = dict(npc, touch=merge_contexts(touches))
        body = self.render_merged(group) if group is not None else self.render(conversation, presentation_check, shop_call_name)
        return self._wrap_npc(npc, body)

    def render_npc_metadata_file(self, npc):
        if npc.get('kind') != 'NPC':
            raise ValueError('NPCの出現記録を選択してください。')
        from reconstruction.emulator_profiles import profile
        initialization = render_npc_initialization([npc], profile('entity_metadata.json', self._target))
        if not initialization and not metadata_values(npc):
            raise ValueError('0x0ADFのグループ・タイトルが未観測か、命令化できません。')
        body = self.templates['npc_metadata_only'] + '\n' + self.templates['end'] + '\n\n' + initialization
        return self._wrap_npc(npc, body)

    def _wrap_npc(self, npc, body):
        state = visibility_state(npc)
        if state == 'ambiguous':
            raise ValueError('NPC初回状態にHIDDENとCLOAKEDの両方を観測。配置状態を手動確認してください。')
        key = 'npc_file_header_' + state if state in ('hidden', 'cloaked') else 'npc_file_header'
        header = self.templates[key].format_map(self.placement_values(npc))
        if body == '':
            return self.templates['npc_empty' + ('_' + state if state in ('hidden', 'cloaked') else '')].format_map(self.placement_values(npc)) + '\n'
        if is_touch(npc):
            touch = npc['touch']
            target = npc.get('warp_target')
            if target and state in ('visible', 'unobserved'):
                values = self.placement_values(npc)
                destination = target.get('map_name')
                if (not isinstance(destination, str) or not re.fullmatch(r'[A-Za-z0-9_@.-]{1,32}', destination)
                        or any(type(target.get(k)) is not int or not 0 <= target[k] <= 1023 for k in ('x', 'y'))):
                    raise ValueError('接触warpの移動先が不正です。')
                code = self.templates['warp_npc'].format_map(dict(values, radius_x=touch['radius_x'], radius_y=touch['radius_y'],
                    destination=base_map_name(destination), destination_x=target['x'], destination_y=target['y'])) + '\n'
                if touch.get('range_provisional', True):
                    code = self.templates['touch_provisional'] + '\n' + code
                return code

            header = self.templates['npc_touch_header' + ('_' + state if state in ('hidden', 'cloaked') else '')].format_map(
                dict(self.placement_values(npc), radius_x=touch['radius_x'], radius_y=touch['radius_y']))
            notes = self.templates['touch_review'] + '\n'
            if touch.get('range_provisional', True):
                notes += self.templates['touch_provisional'] + '\n'
            body = notes + self.templates['touch_label'] + '\n' + body

        lines = [header, *[self.templates['indent'] + line for line in body.rstrip('\n').split('\n')],
                 self.templates['npc_file_footer'].format_map({})]
        result = '\n'.join(lines) + '\n'
        if len(result) > 4 * 1024 * 1024:
            raise ValueError('NPCファイル候補が出力上限を超えています。')
        return result

    @staticmethod
    def _tail_properties(nodes):
        """Compare the entire semantic suffix, ignoring evidence."""
        signatures, complete = {}, {}
        for node in reversed(nodes):
            children = node['children']
            if any(child <= node['id'] or child >= len(nodes) for child in children):
                raise ValueError('Invalid or cyclic dialogue tree')
            payload = [node['kind'], node['fields'], sorted(signatures[child] for child in children)]
            signatures[node['id']] = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                                       ensure_ascii=False).encode('utf-8')).hexdigest()
            kind = node['kind']
            value = bool(children) and all(complete[child] for child in children)
            if kind in ('end', 'loop_continue'):
                value = not children
            elif kind == 'shop_boundary':
                value = bool(node['fields'].get('shop_call_name')) and not children
            elif kind == 'barter_boundary':
                value = bool(node['fields'].get('barter_call_name')) and not children
            elif kind in ('pending', 'boundary', 'ambiguous'):
                value = False
            elif kind in ('menu', 'loop_menu'):
                choices = {nodes[child]['fields']['value'] for child in children if nodes[child]['kind'] == 'choice'}
                value = value and len(choices) == len(node['fields']['options']) and len(children) == len(choices)
                if kind == 'loop_menu':
                    value = False  # A return is not evidence of a complete terminating suffix.
            elif kind in ('number', 'text'):
                expected = 'number_reply' if kind == 'number' else 'text_reply'
                value = value and all(nodes[child]['kind'] == expected for child in children)
            complete[node['id']] = value
        tails = {node['id']: tuple(sorted(signatures[child] for child in node['children'])) for node in nodes}
        return tails, complete

    def _render_nodes(self, nodes, preamble, max_output_chars=4 * 1024 * 1024, max_pending_actions=100000,
                      allow_identical_menu=True, shop_call_name=None, map_name=None, npc_name=None):
        out, output_chars = [], 0
        self._tail_properties(nodes)  # Reject invalid/cyclic source trees before projecting.
        if allow_identical_menu:
            nodes = share_menu_continuations(nodes, max_actions=max_pending_actions)
        nodes = fold_menu_loops(nodes, max_actions=max_pending_actions)
        tails, complete = self._tail_properties(nodes)
        def emit(key, depth=0, fallback=None, **values):
            nonlocal output_chars
            text = self.templates[key if key in self.templates else fallback].format_map(values)
            for line in text.split('\n'):
                formatted = self.templates['indent'] * depth + line
                output_chars += len(formatted) + 1
                if output_chars > max_output_chars:
                    raise ValueError('Merged code exceeds output size limit; no partial code was returned')
                out.append(formatted)
        def schedule(tasks):
            if len(stack) + len(tasks) > max_pending_actions:
                raise ValueError('Merged menu expansion exceeds pending action limit')
            stack.extend(reversed(tasks))
        for key, values in preamble:
            emit(key, **values)
        stack = [('walk', 0, False, False, 0)]
        while stack:
            operation, value, cutin, window_closed, depth = stack.pop()
            if operation == 'emit':
                key, fields = value
                emit(key, depth, **fields)
                continue
            if operation == 'unknown':
                emit('unknown', depth)
                emit('end', depth)
                continue
            if operation == 'walk':
                children = nodes[value]['children']
                if not children:
                    emit('end', depth)
                elif len(children) == 1:
                    stack.append(('node', children[0], cutin, window_closed, depth))
                else:
                    emit('alternatives', depth)
                    tasks = []
                    for number, child in enumerate(children, 1):
                        tasks.extend([('emit', ('alternative', {'number': number}), cutin, window_closed, depth),
                                      ('emit', ('block_open', {}), cutin, window_closed, depth),
                                      ('node', child, cutin, window_closed, depth + 1),
                                      ('emit', ('block_close', {}), cutin, window_closed, depth)])
                    schedule(tasks)
                continue
            node = nodes[value]
            kind, fields = node['kind'], node['fields']
            if 'observed_gap' in node and 'observed_gap' in self.templates:
                emit('observed_gap', depth, duration_ms=node['observed_gap'])
            if kind == 'loop_continue':
                emit('continue', depth)
                continue
            if kind in ('menu', 'loop_menu'):
                if kind == 'loop_menu':
                    emit('loop_review', depth)
                    emit('while_open', depth)
                    stack.append(('emit', ('block_close', {}), cutin, window_closed, depth))
                    depth += 1
                options = fields['options']
                choices = {nodes[child]['fields']['value']: child for child in node['children']
                           if nodes[child]['kind'] == 'choice'}
                emit('menu', depth, options=f'{self._text(":".join(options))},-')
                all_same = (allow_identical_menu and len(choices) == len(options) and len(node['children']) == len(choices)
                            and all(complete[child] for child in choices.values())
                            and len({tails[child] for child in choices.values()}) == 1)
                if len(options) == 1 or all_same or (allow_identical_menu and node.get('shared_response')):
                    if choices:
                        stack.append(('walk', choices[min(choices)], cutin, window_closed, depth))
                    else:
                        emit('pending', depth)
                        emit('unknown', depth)
                        emit('end', depth)
                    continue
                if not choices:
                    emit('pending', depth)
                emit('switch_open', depth)
                tasks = []
                for number in range(1, len(options) + 1):
                    tasks.append(('emit', ('case', {'value': number}), cutin, window_closed, depth + 1))
                    tasks.append(('walk', choices[number], cutin, window_closed, depth + 2) if number in choices
                                 else ('unknown', None, cutin, window_closed, depth + 2))
                    tasks.append(('emit', ('break', {}), cutin, window_closed, depth + 2))
                tasks.extend([('emit', ('block_close', {}), cutin, window_closed, depth), ('emit', ('end', {}), cutin, window_closed, depth)])
                schedule(tasks)
                continue
            if kind in ('number', 'text'):
                emit(kind, depth)
                expected = 'number_reply' if kind == 'number' else 'text_reply'
                replies = [nodes[child] for child in node['children'] if nodes[child]['kind'] == expected]
                if not replies:
                    emit('pending', depth)
                    emit('end', depth)
                    continue
                tasks = []
                for reply in replies:
                    observed = reply['fields']['value'] if kind == 'number' else self._text(reply['fields']['text'])
                    key = 'input_number_observation' if kind == 'number' else 'input_text_observation'
                    tasks.extend([('emit', (key, {'value': observed}), cutin, window_closed, depth),
                                  ('emit', ('block_open', {}), cutin, window_closed, depth),
                                  ('walk', reply['id'], cutin, window_closed, depth + 1),
                                  ('emit', ('block_close', {}), cutin, window_closed, depth)])
                schedule(tasks)
                continue
            if kind in ('end', 'pending', 'boundary', 'ambiguous', 'shop_boundary', 'barter_boundary'):
                if kind == 'pending':
                    emit('pending', depth)
                elif kind == 'boundary':
                    emit('merge_boundary', depth, 'pending')
                elif kind == 'ambiguous':
                    emit('ambiguous', depth)
                elif kind == 'shop_boundary':
                    call_name = fields.get('shop_call_name', shop_call_name)
                    if call_name is not None:
                        if not window_closed:
                            emit('close2', depth)
                        reference = _quote(call_name)
                        if isinstance(map_name, str) and '@' in map_name:
                            reference = self.templates['instance_npc_reference'].format(name=reference)
                        emit('callshop', depth, shop_name=reference)
                    else:
                        emit('shop_boundary', depth)
                elif kind == 'barter_boundary':
                    call_name = fields.get('barter_call_name')
                    if call_name is not None:
                        if not window_closed:
                            emit('close2', depth)
                        reference = _quote(call_name)
                        if isinstance(map_name, str) and '@' in map_name:
                            reference = self.templates['instance_npc_reference'].format(name=reference)
                        emit('callbarter_review', depth, shop_name=reference)
                    else:
                        emit('barter_boundary', depth)
                emit('end', depth)
                continue
            if kind == 'mes':
                window_closed = False
                emit('mes', depth, text=self._text(fields['text']))
            elif kind in ('timeout_warning', 'aborted_wait'):
                emit(kind, depth, prompt_kind=fields['prompt_kind'])
            elif kind in ('quest_set', 'quest_delete'):
                emit(kind, depth, quest_id=fields['quest_id'])
            elif kind == 'quest_wait_review':
                emit(kind, depth)
            elif kind == 'resource_adoption_review':
                emit(kind, depth)
            elif kind == 'zeny_set':
                emit(kind, depth, delta_signed=fields['delta_signed'])
            elif kind in ('map_warp', 'map_warp_review'):
                emit(kind, depth, map_name=_quote(base_map_name(fields['map_name'])),
                     x=fields['x'], y=fields['y'])
            elif kind == 'overhead':
                emit('overhead', depth, text=self._text(fields['text']))
            elif kind == 'unittalk':
                emit('unittalk', depth, text=self._text(fields['text']))
            elif kind == 'colored_speech':
                emit('colored_speech', depth, color_hex=f"{fields['color']:08X}",
                     text=self._text(fields['text']))
            elif kind == 'announcement':
                template, values = announcement_values(fields)
                values = dict(values, text=self._text(fields['text']))
                emit(template, depth, **values)
            elif kind in ('emotion', 'effect', 'effect_remove'):
                emit(kind, depth, value=fields['value'])
            elif kind == 'effect_value':
                emit('effect_value', depth, effect_id=fields['effect_id'], value=fields['value'])
            elif kind == 'event_marker':
                emit('event_marker', depth, x=fields['x'], y=fields['y'],
                     state=fields['state'], kind=fields['kind'])
            elif kind == 'hat_effect':
                emit('hat_effect', depth, enabled=fields['enabled'], effect_id=fields['effect_id'])
            elif kind == 'status_enter':
                emit('status_enter', depth, effect_id=fields['effect_id'],
                     remaining_ms=fields['remaining_ms'], value1=fields['value1'],
                     value2=fields['value2'], value3=fields['value3'],
                     tick=fields.get('tick', 'n/a'))
            elif kind == 'mercenary':
                emit('mercenary', depth, name=_quote(fields['name']), duration=fields['duration'])
            elif kind == 'classchange':
                if npc_name:
                    emit('script_rendered',depth,text=render_display(dict(name=npc_name,map_name=map_name),{'class_id':fields['class_id']},self.templates))
                else:
                    emit('classchange', depth, class_id=fields['class_id'], kind=fields['kind'])
            elif kind == 'script_command':
                text = render_command(fields, self.templates)
                # Use the same bounded emitter as every other command.
                emit('script_rendered', depth, text=text)
            elif kind == 'npc_display_action':
                emit('script_rendered',depth,text=render_display(fields['target'],fields['display'],self.templates,outside=fields['outside']))
            elif kind == 'visibility_action':
                target = fields.get('target')
                for command in fields['commands']:
                    if command not in ('hideonnpc', 'hideoffnpc', 'cloakonnpc', 'cloakoffnpc'):
                        raise ValueError('Unsupported visibility command')
                    if target:
                        reference = _quote(base_npc_name(target['name'], target['map_name']))
                        if '@' in (target['map_name'] or ''):
                            reference = self.templates['instance_npc_reference'].format(name=reference)
                        emit(command + '_target', depth, target=reference)
                    else:
                        emit(command, depth)
            elif kind == 'unittalk_target':
                target = fields['target']
                reference = _quote(base_npc_name(target['name'], target['map_name']))
                if '@' in (target['map_name'] or ''):
                    reference = self.templates['instance_npc_reference'].format(name=reference)
                emit('unittalk_target', depth, text=self._text(fields['text']), target=reference)
            elif kind in ('dialogue_size','dialogue_position','dialogue_alignment'):
                emit(kind, depth, **fields)
            elif kind == 'progress_action':
                if not 0 <= fields['seconds'] <= 2147483 or not 0 <= fields['color'] <= 0xffffffff:
                    raise ValueError('Invalid progressbar values')
                emit('progress_action', depth, seconds=fields['seconds'], color=f"0x{fields['color']:06X}")
            elif kind == 'status_action':
                entry = self.status_ids.get(str(fields['effect_id']))
                if entry and fields['flag'] == 0:
                    emit('status_end', depth, symbol=entry['script_id'])
                elif (entry and entry['argument_policy'] == 'val1_only' and fields['flag'] == 1 and fields['value2'] == fields['value3'] == 0
                      and fields['remaining_ms'] != 9999 and 0 <= fields['remaining_ms'] <= 2147483647
                      and 0 <= fields['value1'] <= 2147483647):
                    emit('status_start', depth, symbol=entry['script_id'], duration=fields['remaining_ms'], value=fields['value1'])
                else:
                    emit('status_review', depth, evidence=json.dumps(fields, ensure_ascii=True, sort_keys=True))
            elif kind == 'action_wait_review':
                emit('action_wait_review', depth)
            elif kind == 'progressbar':
                emit('progressbar', depth, seconds=fields['seconds'], color=fields['color'])
            elif kind == 'viewpoint':
                supported = (type(fields['kind']) is int and fields['kind'] in (1, 2)
                             and all(type(fields[key]) is int and 0 <= fields[key] <= 1023 for key in ('x', 'y'))
                             and type(fields['marker_id']) is int and 0 <= fields['marker_id'] <= 255
                             and type(fields['color']) is int and 0 <= fields['color'] <= 0xffffffff)
                values = {key: fields[key] for key in ('kind', 'x', 'y', 'marker_id', 'color')}
                if supported:
                    values['color'] = f'0x{fields["color"] & 0xffffff:06X}'
                emit('viewpoint' if supported else 'viewpoint_observation', depth, **values)
            elif kind == 'sound':
                emit('sound', depth, sound=_quote(fields['sound']), mode=fields['mode'], interval=fields['interval'])
            elif kind == 'cutin':
                cutin = fields['position'] != 255
                emit('cutin', depth, image=_quote(fields['image']), position=fields['position'])
            elif kind == 'close':
                if (shop_call_name is not None
                        or any(nodes[child]['kind'] == 'shop_boundary'
                               and nodes[child]['fields'].get('shop_call_name') for child in node['children'])
                        or any(nodes[child]['kind'] == 'barter_boundary'
                               and nodes[child]['fields'].get('barter_call_name') for child in node['children'])):
                    stack.append(('walk', node['id'], cutin, window_closed, depth))
                    continue
                emit('close', depth)
                if any(nodes[child]['kind'] == 'shop_boundary' for child in node['children']):
                    emit('shop_boundary', depth)
                if any(nodes[child]['kind'] == 'barter_boundary' for child in node['children']):
                    emit('barter_boundary', depth)
                continue
            elif kind == 'close2':
                window_closed = True
                emit('close2_observed', depth)
                emit('close2', depth)
            elif kind == 'post_close_warp':
                if (not isinstance(fields.get('map_name'), str)
                        or not re.fullmatch(r'[A-Za-z0-9_@.-]{1,32}', fields['map_name'])
                        or any(type(fields.get(key)) is not int or not 0 <= fields[key] <= 1023 for key in ('x', 'y'))):
                    emit('ambiguous', depth)
                    emit('end', depth)
                    continue
                source = fields.get('source_map_name', map_name)
                reference = _quote(base_map_name(fields['map_name']))
                key = 'post_close_warp'
                if '@' in fields['map_name']:
                    if isinstance(source, str) and '@' in source:
                        reference = self.templates['instance_map_reference'].format(name=reference)
                    else:
                        key = 'instance_entry_warp'
                emit(key, depth, map_name=reference, x=fields['x'], y=fields['y'])
            elif kind in ('next', 'clear'):
                emit(kind, depth)
            else:
                emit('ambiguous', depth)
                emit('end', depth)
                continue
            stack.append(('walk', node['id'], cutin, window_closed, depth))
        return '\n'.join(out) + '\n'

    def render_merged(self, group, max_output_chars=4 * 1024 * 1024, max_pending_actions=100000, *, include_initialization=True):
        if group is None:
            key = 'merge_unavailable' if 'merge_unavailable' in self.templates else 'ambiguous'
            nodes = [dict(id=0, kind='root', fields={}, children=[])]
            return self._render_nodes(nodes, [(key, {})], max_output_chars, max_pending_actions)
        if 'merged_header' in self.templates:
            preamble = [('merged_header', dict(id=group['id'], npc_name=_quote(group['npc']['name']),
                         map_name=_quote(group['npc']['map_name'] or ''), observations=len(group['contributions'])))]
        else:
            first = next(node['evidence'][0] for node in group['nodes'] if node['evidence'])
            preamble = [('header', dict(id=group['id'], actor_id=first['actor_id']))]
        if group.get('presentation_check', {}).get('conflicts'):
            preamble.append(('presentation_warning', dict(count=group['presentation_check']['conflicts'])))
        if group.get('timeout_normalizations'):
            preamble.append(('timeout_normalized_warning', dict(count=len(group['timeout_normalizations']))))
        late_count = sum(len(row['conversation'].get('late_replies', [])) for row in group['contributions'])
        if late_count:
            preamble.append(('late_reply_warning', dict(count=late_count)))
        from reconstruction.dialogue import Conversation
        for contribution in group['contributions']:
            candidate = Conversation(**contribution['conversation'])
            validate_external(candidate)
            preamble.extend(('action_observation', dict(evidence=json.dumps(row, ensure_ascii=True, sort_keys=True))) for row in candidate.actions)
            preamble.extend(self._external_preamble(candidate))
        resource_trials = [dict(capture_session=row['capture_session'], conversation_id=row['conversation_id'],
            source_ref=row['source_ref'], observations=row['conversation'].get('resource_observations', []))
            for row in group['contributions'] if not row.get('partial_observation')]
        preamble.extend(self._resource_preamble(resource_trials))
        resource_variants = {json.dumps([[row['kind'], row['fields'], row.get('after_step_index')]
                                        for row in trial['observations']],
                            sort_keys=True, ensure_ascii=False) for trial in resource_trials}
        body = self._render_nodes(group['nodes'], preamble, max_output_chars, max_pending_actions,
                                  allow_identical_menu=len(resource_variants) <= 1,
                                  map_name=group['npc'].get('map_name'), npc_name=group['npc'].get('name'))
        if include_initialization:
            from reconstruction.emulator_profiles import profile
            result = append_initialization(
                body, [row['conversation'].get('npc', {}) for row in group['contributions']],
                profile('entity_metadata.json', self._target))
        else:
            result = body
        if len(result) > max_output_chars:
            raise ValueError('Merged code exceeds output size limit; no partial code was returned')
        return result

    def render_groups(self, groups, max_output_chars=4 * 1024 * 1024, max_pending_actions=100000):
        codes, errors = [], []
        for group in groups:
            try:
                codes.append(self.render_merged(group, max_output_chars, max_pending_actions))
            except ValueError as exc:
                codes.append(None)
                errors.append(dict(group_id=group['id'], message=str(exc)))
        return dict(auriga=codes, generation_errors=errors)
