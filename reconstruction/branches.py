"""Observed-path tries retaining contradictions and input response evidence."""
from reconstruction.touch import is_touch, compare_conversation_trials, format_trial_comparison
from reconstruction.actor_appearance import declaration_class
from reconstruction.conversation_actions import validate_actions
import hashlib
import json
import math
import re
from copy import deepcopy
from bisect import bisect_right
from dataclasses import asdict
from reconstruction.timing import build_timeline
from reconstruction.quests import valid_counter_fields

PRESENTATION_KINDS = {'dialogue_size', 'dialogue_position', 'dialogue_alignment', 'emotion', 'effect', 'effect_value', 'effect_remove', 'event_marker', 'hat_effect', 'achievement', 'item_preview', 'mercenary', 'sound', 'cutin', 'classchange', 'progressbar', 'viewpoint', 'overhead', 'announcement', 'unittalk', 'colored_speech', 'visibility_action', 'status_action', 'progress_action', 'unittalk_target', 'action_wait_review', 'script_command', 'npc_display_action'}


def validate_external(conversation):
    seen = set()
    end_index = conversation.termination.get('packet_index')
    if end_index is None and conversation.status in ('closed', 'cancelled') and conversation.steps:
        end_index = conversation.steps[-1]['packet_index']
    for row in conversation.external_presentations:
        if 'adoption_confirmed' not in row:
            row['adoption_confirmed'] = False
        anchor = row.get('after_step_index')
        if (row.get('context') != 'external_candidate' or row.get('cause_confirmed') is not False
                or row.get('association_basis') != 'same_flow_active_dialogue_external_target'
                or row.get('conversation_id') != conversation.id or row.get('conversation_actor_id') != conversation.actor_id
                or row.get('capture_session') != conversation.capture_session or row.get('flow_id') != conversation.flow_id
                or row.get('direction') != 'RECV' or row.get('actor_id') == conversation.actor_id
                or row.get('entity_kind') != 'NPC' or row.get('target_observed') is not True
                or row.get('kind') not in ('emotion', 'effect', 'effect_value', 'effect_remove', 'event_marker',
                                           'hat_effect', 'sound', 'overhead', 'unittalk', 'colored_speech',
                                           'mercenary')
                or row['adoption_confirmed'] is not True and row['adoption_confirmed'] is not False
                or type(anchor) is not int or not 0 <= anchor < len(conversation.steps)
                or row['packet_index'] in seen or not math.isfinite(row['timestamp'])
                or not conversation.steps[anchor]['packet_index'] < row['packet_index']
                or (end_index is not None and row['packet_index'] > end_index)
                or row['timestamp'] < conversation.steps[anchor]['timestamp']
                or any(row.get('npc', {}).get(key) != conversation.npc.get(key) for key in ('map_name', 'map_generation'))):
            raise ValueError('Invalid external presentation candidate scope')
        seen.add(row['packet_index'])
        source_key = row.get('conversation_entity_key')
        target_key = row.get('target_entity_key')
        if source_key is not None or target_key is not None:
            expected_source = [conversation.capture_session, conversation.npc.get('connection'),
                conversation.npc.get('map_generation'), conversation.actor_id, conversation.npc.get('appearance')]
            expected_target = [row['capture_session'], row['connection'], row['npc'].get('map_generation'),
                row['actor_id'], row['npc'].get('appearance')]
            if source_key != expected_source or target_key != expected_target:
                raise ValueError('External presentation appearance evidence does not match')


def validate_resources(conversation):
    if len(conversation.resource_observations) > 512:
        raise ValueError('Resource observation capacity exceeded')
    for row in conversation.resource_observations:
        fields, kind = row['fields'], row['kind']
        if 'adoption_confirmed' not in row:
            row['adoption_confirmed'] = False
        if (row['direction'] != 'RECV' or row['capture_session'] != conversation.capture_session
                or row['flow_id'] != conversation.flow_id or row['cause_confirmed'] is not False
                or row['adoption_confirmed'] is not True and row['adoption_confirmed'] is not False
                or not math.isfinite(row['timestamp']) or row['timestamp'] < conversation.started
                or type(row['packet_index']) is not int or row['packet_index'] < 0):
            raise ValueError('Invalid resource observation scope')
        anchor = row.get('after_step_index')
        if anchor is not None and (type(anchor) is not int or not 0 <= anchor < len(conversation.steps)):
            raise ValueError('Invalid resource observation anchor')
        if kind == 'zeny':
            valid = (set(fields) == {'value', 'delta', 'delta_known'} and type(fields['value']) is int
                     and fields['value'] >= 0 and type(fields['delta']) is int and type(fields['delta_known']) is bool)
        elif kind in ('item_gain', 'item_loss'):
            valid = (set(fields) == {'item_id', 'amount', 'index'}
                     and all(type(value) is int for value in fields.values())
                     and fields['item_id'] > 0 and 0 < fields['amount'] <= 65535 and fields['index'] >= 0)
        elif kind == 'map':
            valid = (set(fields) == {'map_name', 'x', 'y'} and isinstance(fields['map_name'], str)
                     and len(fields['map_name']) <= 32 and type(fields['x']) is int and type(fields['y']) is int
                     and 0 <= fields['x'] <= 65535 and 0 <= fields['y'] <= 65535)
        elif kind == 'quest_count':
            valid = valid_counter_fields(fields)
        elif kind in ('quest_add', 'quest_delete', 'quest_state'):
            expected = {'quest_id'} if kind == 'quest_delete' else {'quest_id', 'state'}
            if kind == 'quest_add':
                expected |= {'start_time', 'deadline', 'objective_count', 'objective_payload_hex'}
            valid = (set(fields) == expected and type(fields['quest_id']) is int and 0 <= fields['quest_id'] <= 0xffffffff
                     and (kind == 'quest_delete' or type(fields['state']) is int and 0 <= fields['state'] <= 255))
            if kind == 'quest_add':
                valid = (valid and type(fields['objective_count']) is int and 0 <= fields['objective_count'] <= 3
                    and all(type(fields[key]) is int and 0 <= fields[key] <= 0xffffffff for key in ('start_time', 'deadline'))
                    and isinstance(fields['objective_payload_hex'], str)
                    and len(fields['objective_payload_hex']) in (180, 252, 276)
                    and re.fullmatch('[0-9a-f]*', fields['objective_payload_hex']) is not None)
        else:
            valid = False
        if not valid:
            raise ValueError('Invalid resource observation fields')


def validate_parallel(conversation):
    seen = set()
    for row in conversation.parallel_presentations:
        index = row['prompt_step_index']
        if type(index) is not int or not 0 <= index < len(conversation.steps):
            raise ValueError('Invalid parallel prompt')
        prompt = conversation.steps[index]
        reply = prompt.get('reply')
        if (prompt['kind'] not in ('menu', 'next', 'number', 'text') or type(reply) is not int
                or not index < reply < len(conversation.steps)):
            raise ValueError('Unresolved parallel prompt')
        response = conversation.steps[reply]
        if (row['kind'] not in PRESENTATION_KINDS or row['context'] != 'input_wait'
                or row['direction'] != 'RECV' or row['capture_session'] != conversation.capture_session
                or row['flow_id'] != conversation.flow_id
                or not (row['actor_id'] == conversation.actor_id or
                        row['kind'] == 'announcement' and row['actor_id'] is None
                        and row.get('association_basis') == 'active_dialogue_same_flow'
                        and row.get('conversation_id') == conversation.id and not row['target_observed'])
                or row['packet_index'] in seen
                or not prompt['packet_index'] < row['packet_index'] < response['packet_index']
                or not math.isfinite(row['timestamp'])
                or not prompt['timestamp'] <= row['timestamp'] <= response['timestamp']):
            raise ValueError('Invalid parallel observation scope or ordering')
        seen.add(row['packet_index'])


def check_presentations(trials):
    """Compare complete matching dialogue paths, without guessing event causes."""
    paths = {}
    for key, tokens, parallel in trials:
        skeleton, events, references = [], [], []
        anchors = {}
        for token in tokens:
            if token['kind'] in PRESENTATION_KINDS:
                events.append(dict(after_token_index=len(skeleton) - 1,
                                   kind=token['kind'], fields=deepcopy(token['fields'])))
                references.append(token['evidence'])
            else:
                anchors[token['evidence']['step_index']] = len(skeleton)
                skeleton.append([token['kind'], token['fields']])
        for record in parallel:
            external = record.get('context') == 'external_candidate'
            if external and record['kind'] == 'unittalk' and any(
                    token['kind'] == 'unittalk_target' and token['evidence']['packet_index'] == record['packet_index'] for token in tokens):
                continue
            index = record['after_step_index'] if external else record['prompt_step_index']
            position = max((step for step in anchors if step is not None and step <= index), default=None)
            after = anchors.get(position, -1) if external else anchors[index]
            events.append(dict(after_token_index=after, track='external_candidate' if external else 'input_wait',
                               kind=record['kind'], fields=deepcopy(record['fields'])))
            if external:
                events[-1]['target'] = {key: record['npc'].get(key) for key in
                                       ('map_name', 'name', 'class_id', 'x', 'y', 'direction')}
            references.append(dict(record, source_ref=key[0], conversation_id=key[2], step_index=None))
        ordered = sorted(zip(events, references), key=lambda row: row[1]['packet_index'])
        events = [row[0] for row in ordered]
        references = [row[1] for row in ordered]
        path_hash = hashlib.sha256(json.dumps(skeleton, sort_keys=True,
                                 ensure_ascii=False).encode('utf-8')).hexdigest()
        path = paths.setdefault(path_hash, dict(variants={}, count=0))
        signature = json.dumps(events, sort_keys=True, ensure_ascii=False)
        variant = path['variants'].setdefault(signature, dict(events=events, observations=[]))
        variant['observations'].append(dict(source_ref=key[0], capture_session=key[1],
                                            conversation_id=key[2], event_evidence=references))
        path['count'] += 1
    checks = []
    for path_hash, path in sorted(paths.items()):
        variants = [path['variants'][key] for key in sorted(path['variants'])]
        if not any(variant['events'] for variant in variants):
            continue
        status = ('insufficient_observations' if path['count'] < 2 else
                  'conflicting_observations' if len(variants) > 1 else 'consistent_observations')
        checks.append(dict(path_hash=path_hash, status=status, trials=path['count'], variants=variants,
                           cause_confirmed=False))
    return dict(comparisons=checks,
                conflicts=sum(row['status'] == 'conflicting_observations' for row in checks),
                cause_confirmed=False)


def npc_identity(conversation, source_ref=''):
    keys = ('map_name', 'name', 'class_id', 'x', 'y', 'direction')
    npc = dict(conversation.npc)
    npc['class_id'] = declaration_class(npc)
    if npc.get('map_name') and npc.get('name') and all(npc.get(key) is not None for key in keys):
        return dict(scope='identified_placement', **{key: npc[key] for key in keys})
    # An identified entity appearance is usable within its own capture even when
    # the initial map name was not observed. It must never bridge separate logs.
    local_keys = ('name', 'class_id', 'x', 'y', 'direction', 'connection', 'map_generation', 'appearance')
    if npc.get('name') and all(npc.get(key) is not None for key in local_keys):
        return dict(scope='capture_entity', source_ref=source_ref, capture_session=conversation.capture_session,
                    actor_id=conversation.actor_id, map_name=npc.get('map_name'), **{key: npc[key] for key in local_keys})
    return None


def observation_key(source_ref, conversation):
    return (source_ref, conversation.capture_session, conversation.id)


def _reference(source_ref, conversation, step, index):
    return dict(source_ref=source_ref, capture_session=conversation.capture_session, conversation_id=conversation.id,
                actor_id=conversation.actor_id, step_index=index, packet_index=step['packet_index'],
                packet_id=step['packet_id'], timestamp=step['timestamp'], connection=step['connection'])


def conversation_path(source_ref, conversation, strict=True):
    tokens = []
    continuing_close = None
    steps = conversation.steps
    validate_actions(conversation)
    scheduled = {}
    for row in conversation.actions:
        fields = {key: value for key, value in row['fields'].items() if not (row['kind'] == 'status_action' and key == 'tick')}
        if row['kind'] == 'visibility_action':
            fields = {key: fields[key] for key in ('commands', 'target')}
        scheduled.setdefault(row['after_step_index'], []).append((row['kind'], fields, row))
    for anchor in list(scheduled):
        if steps[anchor]['kind'] in ('next', 'menu', 'number', 'text'):
            reply = steps[anchor].get('reply')
            rows = scheduled.pop(anchor)
            if type(reply) is int and anchor < reply < len(steps) and steps[reply].get('reply_to') == anchor:
                for kind, fields, row in rows:
                    scheduled.setdefault(reply, []).extend([('action_wait_review', {}, row), (kind, fields, row)])
    for rows in scheduled.values():
        rows.sort(key=lambda row: row[2]['packet_index'])
    quests = {}
    for row in conversation.resource_observations:
        if row['kind'] not in ('quest_add', 'quest_delete'):
            continue
        anchor = row.get('after_step_index')
        if type(anchor) is not int or not 0 <= anchor < len(steps):
            continue
        deferred = steps[anchor]['kind'] in ('next', 'menu', 'number', 'text')
        if deferred:
            reply = steps[anchor].get('reply')
            if type(reply) is not int or not anchor < reply < len(steps) or steps[reply].get('reply_to') != anchor:
                continue
            anchor = reply
        quests.setdefault(anchor, []).append((row, deferred))
    scripted_packets = {row['packet_index'] for row in conversation.actions
                        if row.get('fields', {}).get('command') in ('getitem', 'getitem2', 'delitem', 'delequip')}
    adopted = {}
    for row in conversation.resource_observations:
        if row.get('adoption_confirmed') is not True or row['kind'] not in ('zeny', 'item_gain', 'item_loss', 'map'):
            continue
        if row['kind'] in ('item_gain', 'item_loss') and row['packet_index'] in scripted_packets:
            continue
        if row['kind'] == 'zeny' and not row['fields'].get('delta_known'):
            continue
        anchor = row.get('after_step_index')
        if type(anchor) is not int or not 0 <= anchor < len(steps):
            continue
        deferred = steps[anchor]['kind'] in ('next', 'menu', 'number', 'text')
        if deferred:
            reply = steps[anchor].get('reply')
            if type(reply) is not int or not anchor < reply < len(steps) or steps[reply].get('reply_to') != anchor:
                continue
            anchor = reply
        adopted.setdefault(anchor, []).append((row, deferred))
    def append_quests(anchor):
        events = [(row['packet_index'], kind, fields, row, False) for kind, fields, row in scheduled.get(anchor, [])]
        events.extend((row['packet_index'], 'quest', {}, row, deferred) for row, deferred in quests.get(anchor, []))
        events.extend((row['packet_index'], 'adopted', {}, row, deferred) for row, deferred in adopted.get(anchor, []))
        for _, kind, fields, row, deferred in sorted(events, key=lambda event: event[0]):
            reference = _reference(source_ref, conversation, row, None)
            if kind == 'adopted':
                if deferred:
                    tokens.append(dict(kind='resource_adoption_review', fields={}, evidence=reference))
                if row['kind'] == 'zeny':
                    tokens.append(dict(kind='zeny_set', fields={'delta_signed': f"{row['fields']['delta']:+d}"},
                                       evidence=reference))
                elif row['kind'] == 'map':
                    values = dict(map_name=row['fields']['map_name'], x=row['fields']['x'], y=row['fields']['y'])
                    tokens.append(dict(kind='map_warp_review' if '@' in values['map_name'] else 'map_warp',
                                       fields=values, evidence=reference))
                elif row['kind'] == 'item_gain':
                    tokens.append(dict(kind='script_command',
                        fields=dict(command='getitem', arguments=dict(item_id=row['fields']['item_id'],
                                                                      amount=row['fields']['amount']),
                                    review_only=False, review_reason=''), evidence=reference))
                else:
                    tokens.append(dict(kind='script_command',
                        fields=dict(command='delitem', arguments=dict(item_id=row['fields']['item_id'],
                                                                     amount=row['fields']['amount']),
                                    review_only=False, review_reason=''), evidence=reference))
                continue
            if kind != 'quest':
                tokens.append(dict(kind=kind, fields=deepcopy(fields), evidence=reference))
                continue
            if deferred:
                tokens.append(dict(kind='quest_wait_review', fields={}, evidence=reference))
            tokens.append(dict(kind='quest_set' if row['kind'] == 'quest_add' else 'quest_delete',
                               fields=dict(quest_id=row['fields']['quest_id']), evidence=reference))
    if len(steps) > 2048:
        raise ValueError('Conversation step capacity exceeded')
    for i, step in enumerate(steps):
        append_quests(i - 1)
        kind, fields = step['kind'], step['fields']
        if kind == 'open':
            if i != 0:
                raise ValueError('Unexpected conversation open')
            continue
        if kind in ('next', 'menu', 'number', 'text') and step.get('closed_without_reply'):
            if any(row.get('timeout_suspected') and row.get('timeout_prompt_step_index') == i for row in steps[i + 1:]):
                tokens.append(dict(kind='aborted_wait', fields={'prompt_kind': kind},
                                   evidence=_reference(source_ref, conversation, step, i)))
                continue
        if kind in ('continue', 'choice', 'number_reply', 'text_reply'):
            if i == 0 or step.get('reply_to') != i - 1 or steps[i - 1].get('reply') != i:
                raise ValueError('Reply is not adjacent to the matching prompt')
            if kind == 'continue':
                if steps[i - 1]['kind'] != 'next':
                    raise ValueError('Continue has no next prompt')
                continue
            if kind == 'choice':
                fields = {'value': fields['value']}
                if steps[i - 1]['kind'] != 'menu' or not 1 <= fields['value'] <= len(steps[i - 1]['fields']['options']):
                    raise ValueError('Invalid menu response')
            elif kind == 'number_reply':
                if steps[i - 1]['kind'] != 'number':
                    raise ValueError('Number reply has no input prompt')
                fields = {'value': fields['value']}
            else:
                if steps[i - 1]['kind'] != 'text':
                    raise ValueError('Text reply has no input prompt')
                fields = {'text': fields['text']}
        elif kind == 'menu':
            fields = {'options': fields['options']}
        elif kind == 'dismiss':
            if continuing_close is not None and step.get('reply_to') == continuing_close:
                continue
            break
        elif kind == 'post_close_warp':
            if continuing_close is None or step.get('after_close_reply') is not True:
                raise ValueError('Map continuation has no matched close reply')
        elif kind not in ({'mes', 'next', 'close', 'clear', 'number', 'text'} | PRESENTATION_KINDS):
            raise ValueError('Unsupported conversation event')
        reference = _reference(source_ref, conversation, step, i)
        emitted_kind = kind
        if kind == 'close':
            if step.get('timeout_suspected'):
                tokens.append(dict(kind='timeout_warning', fields={'prompt_kind': step.get('timeout_prompt_kind', 'unknown')},
                                   evidence=reference))
            valid_ack = (step.get('reply') == i + 1 and i + 1 < len(steps)
                         and steps[i + 1]['kind'] == 'dismiss' and steps[i + 1].get('reply_to') == i)
            followup = (any(row.get('after_close_reply') for row in steps[i + 2:])
                        or conversation.termination.get('after_close_reply') is True
                        or any(row.get('after_close_reply') for row in conversation.actions)
                        or any(row.get('after_close_reply') is True and row['kind'] in ('quest_add', 'quest_delete')
                               for row in conversation.resource_observations))
            if valid_ack and followup and not step.get('timeout_suspected'):
                continuing_close, emitted_kind = i, 'close2'
        tokens.append(dict(kind=emitted_kind, fields=deepcopy(fields), evidence=reference))
        if kind == 'close':
            if emitted_kind == 'close':
                break
        if kind in ('next', 'menu', 'number', 'text'):
            expected = {'next': 'continue', 'menu': 'choice', 'number': 'number_reply', 'text': 'text_reply'}[kind]
            valid = (step.get('reply') == i + 1 and i + 1 < len(steps)
                     and steps[i + 1]['kind'] == expected and steps[i + 1].get('reply_to') == i)
            if valid and kind == 'menu':
                valid = 1 <= steps[i + 1]['fields']['value'] <= len(fields['options'])
            if not valid:
                if strict and step.get('reply') is not None:
                    raise ValueError('Prompt reply is inconsistent')
                tokens.append(dict(kind='pending', fields={}, evidence=reference))
                break
    else:
        append_quests(len(steps) - 1)
    if (not tokens and conversation.status not in ('shop_opened', 'barter_opened')
            and not is_touch(conversation.npc)):
        raise ValueError('No supported conversation content')
    terminal = ('boundary' if conversation.status == 'map_changed' else
                'barter_boundary' if conversation.status == 'barter_opened' else
                'shop_boundary' if conversation.status == 'shop_opened' else 'end')
    reference = (tokens[-1]['evidence'] if tokens else
                 _reference(source_ref, conversation, steps[0], 0) if steps else
                 _reference(source_ref, conversation, conversation.termination, None))
    if terminal in ('boundary', 'shop_boundary', 'barter_boundary') and conversation.termination:
        reference = _reference(source_ref, conversation, conversation.termination, None)
    terminal_fields = {}
    if terminal == 'barter_boundary' and conversation.termination.get('barter_call_name'):
        name = conversation.termination['barter_call_name']
        if not isinstance(name, str) or not re.fullmatch(r'GPA_B[0-9a-f]{12}', name):
            raise ValueError('Invalid observed-barter candidate name')
        terminal_fields = {'barter_call_name': name}
    if terminal == 'shop_boundary' and conversation.termination.get('shop_call_name'):
        name = conversation.termination['shop_call_name']
        if not isinstance(name, str) or not re.fullmatch(r'GPA_S[0-9a-f]{12}', name):
            raise ValueError('Invalid observed-shop candidate name')
        terminal_fields = {'shop_call_name': name}
    if terminal == 'boundary' and is_touch(conversation.npc) and conversation.termination.get('fields'):
        tokens.append(dict(kind='post_close_warp', fields=deepcopy(conversation.termination['fields']), evidence=reference))
        terminal = 'end'
    if terminal == 'boundary' and continuing_close is not None and conversation.termination.get('after_close_reply'):
        fields = conversation.termination.get('fields', {})
        tokens.append(dict(kind='post_close_warp', fields=deepcopy(fields), evidence=reference))
        terminal = 'end'
    tokens.append(dict(kind=terminal, fields=terminal_fields, evidence=reference))
    return tokens


def _wait_layout_signature(actions, steps, index):
    """Exact ordered wait observations, distinct from commands deferred past replies."""
    if type(index) is not int or not 0 <= index < len(steps):
        return None
    prompt = steps[index]
    rows = [row for row in actions if row['kind'] in
            ('dialogue_size', 'dialogue_position', 'dialogue_alignment')
            and row['after_step_index'] == index]
    if not rows:
        return ()
    end = prompt.get('reply')
    if type(end) is not int or not index < end < len(steps):
        end = next((i for i in range(index + 1, len(steps))
                    if steps[i].get('timeout_suspected')
                    and steps[i].get('timeout_prompt_step_index') == index), None)
    if end is None:
        return None
    ordered = sorted(rows, key=lambda row: row['packet_index'])
    packets = set()
    previous_time = prompt['timestamp']
    for row in ordered:
        if (row['packet_index'] in packets
                or not prompt['packet_index'] < row['packet_index'] < steps[end]['packet_index']
                or not previous_time <= row['timestamp'] <= steps[end]['timestamp']):
            return None
        packets.add(row['packet_index'])
        previous_time = row['timestamp']
    return tuple((row['kind'], json.dumps(row['fields'], sort_keys=True, ensure_ascii=True))
                 for row in ordered)


def _timeout_prefix(source_ref, conversation):
    closes = [step for step in conversation.steps if step.get('timeout_suspected')
              and type(step.get('timeout_prompt_step_index')) is int]
    if not closes or conversation.parallel_presentations or conversation.external_presentations:
        return None
    index = closes[0]['timeout_prompt_step_index']
    if not 0 <= index < len(conversation.steps) or not conversation.steps[index].get('closed_without_reply'):
        return None
    prompt = conversation.steps[index]
    validate_actions(conversation)
    waiting = [row for row in conversation.actions if row['kind'] in
               ('dialogue_size', 'dialogue_position', 'dialogue_alignment')
               and row['after_step_index'] == index]
    if _wait_layout_signature(conversation.actions, conversation.steps, index) is None:
        return None
    prior_actions = [row for row in conversation.actions if row not in waiting]
    if any(type(row.get('after_step_index')) is not int or row['after_step_index'] >= index
           or row['packet_index'] >= prompt['packet_index'] or row['timestamp'] > prompt['timestamp']
           for row in [*conversation.resource_observations, *prior_actions]):
        return None
    projected = deepcopy(conversation)
    projected.actions = deepcopy(prior_actions)
    projected.steps = projected.steps[:index + 1]
    projected.status, projected.termination, projected.late_replies = 'observing', {}, []
    for step in projected.steps:
        for name in ('timeout_suspected', 'timeout_prompt_kind', 'timeout_prompt_step_index', 'closed_without_reply'):
            step.pop(name, None)
    tokens = conversation_path(source_ref, projected, strict=False)
    return [token for token in tokens if token['kind'] not in ('end', 'pending')]


def _prefix_hashes(tokens):
    digest = hashlib.sha256()
    for index, token in enumerate(tokens, 1):
        kind = 'close' if token['kind'] == 'close2' else token['kind']
        encoded = json.dumps([kind, token['fields']], sort_keys=True, ensure_ascii=True).encode('ascii')
        digest.update(len(encoded).to_bytes(4, 'little'))
        digest.update(encoded)
        yield index, digest.hexdigest()


def _resource_prefix_hashes(tokens, resources):
    """Hash ordered evidence strictly before each token, ignoring capture-specific numbering."""
    positions = [(token['evidence']['step_index'], index) for index, token in enumerate(tokens)
                 if token['evidence']['step_index'] is not None]
    steps = [step for step, _ in positions]
    events = []
    for row in resources:
        index = bisect_right(steps, row['after_step_index']) - 1
        anchor = positions[index][1] if index >= 0 else -1
        events.append((anchor, row['packet_index'], row['kind'], row['fields']))
    events.sort(key=lambda row: row[:2])
    digest, pending = hashlib.sha256(), 0
    for length in range(1, len(tokens) + 1):
        while pending < len(events) and events[pending][0] < length - 1:
            anchor, _, kind, fields = events[pending]
            encoded = json.dumps([anchor, kind, fields], sort_keys=True, ensure_ascii=True).encode('ascii')
            digest.update(len(encoded).to_bytes(4, 'little'))
            digest.update(encoded)
            pending += 1
        yield length, digest.hexdigest()


def build_merged(observations, max_nodes=100000, max_observations=2000,
                 touch_inferences=None,
                 max_semantic_bytes=32 * 1024 * 1024, max_total_steps=100000):
    """Input is (source_ref, Conversation). Never combine unidentified NPCs."""
    groups, excluded, seen = {}, [], set()
    prepared, timeout_candidates = [], []
    semantic_bytes = 0
    total_steps = 0
    input_capacity_reached = False
    for ordinal, (source_ref, conversation) in enumerate(observations):
        if ordinal >= max_observations:
            input_capacity_reached = True
            break
        source_ref = str(source_ref)
        key = observation_key(source_ref, conversation)
        if key in seen:
            continue
        seen.add(key)
        observation_steps = (len(conversation.steps) + len(conversation.parallel_presentations)
                             + len(conversation.resource_observations) + len(conversation.external_presentations) + len(conversation.late_replies))
        if observation_steps > 2048 or total_steps + observation_steps > max_total_steps:
            excluded.append(dict(source_ref=key[0], capture_session=key[1], conversation_id=key[2],
                                 reason='step_capacity', quality_flags=[]))
            continue
        identity = npc_identity(conversation, source_ref)
        timing = build_timeline(conversation, source_ref)
        reason = None
        timeout = any(step.get('timeout_suspected') for step in conversation.steps)
        if identity is None:
            reason = 'npc_identity_incomplete'
        elif not is_touch(conversation.npc) and (not conversation.observed_open or not conversation.steps or conversation.steps[0]['kind'] != 'open'):
            reason = 'open_unobserved'
        elif conversation.status not in ('closed', 'map_changed', 'shop_opened', 'barter_opened'):
            reason = 'conversation_incomplete'
        elif (set(timing['quality_flags']) - ({'start_unobserved'} if is_touch(conversation.npc) else set())) and not (timeout and set(timing['quality_flags']) <= {'overlapping_prompt', 'unanswered_termination'}):
            reason = 'observation_quality'
        if reason is None:
            try:
                tokens = _timeout_prefix(source_ref, conversation) if timeout else conversation_path(source_ref, conversation)
                if timeout and not tokens:
                    reason = 'timeout_additional_evidence_review'
                else:
                    validate_parallel(conversation)
                    validate_external(conversation)
                    validate_resources(conversation)
            except (ValueError, KeyError, TypeError):
                reason = 'reply_or_layout_conflict'
        if reason:
            excluded.append(dict(source_ref=source_ref, capture_session=conversation.capture_session,
                                 conversation_id=conversation.id, reason=reason, quality_flags=timing['quality_flags']))
            continue
        identity_key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        signature = json.dumps([[token['kind'], token['fields']] for token in tokens],
                               sort_keys=True, ensure_ascii=False)
        original = asdict(conversation)
        size = len(json.dumps(original, sort_keys=True, ensure_ascii=False).encode('utf-8'))
        if semantic_bytes + size > max_semantic_bytes:
            excluded.append(dict(source_ref=key[0], capture_session=key[1], conversation_id=key[2], reason='semantic_capacity'))
            continue
        semantic_bytes += size
        total_steps += observation_steps
        (timeout_candidates if timeout else prepared).append((identity_key, signature, key, identity, tokens, timing, original))
    node_count = 0
    accepted = set()
    for identity_key, _, key, identity, tokens, timing, original in sorted(prepared, key=lambda row: row[:3]):
        group = groups.setdefault(identity_key, dict(npc=identity, nodes=[dict(id=0, kind='root', fields={},
            children={}, evidence=[])], contributions=[], presentation_trials=[]))
        nodes = group['nodes']
        parent = 0
        hashes = [hashlib.sha256(json.dumps([token['kind'], token['fields']], sort_keys=True,
                        ensure_ascii=False).encode('utf-8')).hexdigest() for token in tokens]
        missing = 0
        for index, token_hash in enumerate(hashes):
            child = nodes[parent]['children'].get(token_hash)
            if child is None:
                missing = len(tokens) - index
                break
            parent = child
        if node_count + missing > max_nodes:
            excluded.append(dict(source_ref=key[0], capture_session=key[1], conversation_id=key[2], reason='node_capacity'))
            continue
        parent = 0
        for token, token_hash in zip(tokens, hashes):
            child = nodes[parent]['children'].get(token_hash)
            if child is None:
                child = len(nodes)
                nodes[parent]['children'][token_hash] = child
                nodes.append(dict(id=child, kind=token['kind'], fields=token['fields'], children={}, evidence=[]))
                node_count += 1
            nodes[child]['evidence'].append(token['evidence'])
            parent = child
        group['contributions'].append(dict(source_ref=key[0], capture_session=key[1], conversation_id=key[2],
                                           timeline=timing, conversation=original))
        group['presentation_trials'].append((key, tokens, original['parallel_presentations'] + original['external_presentations']))
        accepted.add(key)
    wanted = {}
    for identity_key, _, key, identity, tokens, timing, original in timeout_candidates:
        length, digest = list(_prefix_hashes(tokens))[-1]
        wanted.setdefault(identity_key, set()).add(length)
    matches = {}
    for identity_key, _, key, identity, tokens, timing, original in sorted(prepared, key=lambda row: row[:3]):
        if key not in accepted or identity_key not in wanted:
            continue
        resource_hashes = _resource_prefix_hashes(tokens, original['resource_observations'])
        for (length, digest), (_, resource_digest) in zip(_prefix_hashes(tokens), resource_hashes):
            if length in wanted[identity_key]:
                prompt_index = tokens[length - 1]['evidence']['step_index']
                layouts = _wait_layout_signature(original['actions'], original['steps'], prompt_index)
                if layouts is None:
                    continue
                entry = matches.setdefault((identity_key, length, digest, resource_digest, layouts), dict(count=0, observation=key))
                entry['count'] += 1
    for identity_key, _, key, identity, tokens, timing, original in sorted(timeout_candidates, key=lambda row: row[:3]):
        length, digest = list(_prefix_hashes(tokens))[-1]
        resource_digest = list(_resource_prefix_hashes(tokens, original['resource_observations']))[-1][1]
        prompt_index = tokens[-1]['evidence']['step_index']
        layouts = _wait_layout_signature(original['actions'], original['steps'], prompt_index)
        match = matches.get((identity_key, length, digest, resource_digest, layouts))
        if not match:
            excluded.append(dict(source_ref=key[0], capture_session=key[1], conversation_id=key[2],
                                 reason='timeout_prefix_unmatched', quality_flags=timing['quality_flags']))
            continue
        group = groups[identity_key]
        normalization = dict(method='timeout_close_removed_prefix_match', matched_prefix_tokens=length,
                             matched_resource_observations=len(original['resource_observations']),
                             matching_observation=list(match['observation']), matched_paths=match['count'])
        if layouts:
            normalization['matched_wait_layout_observations'] = len(layouts)
        group['contributions'].append(dict(source_ref=key[0], capture_session=key[1], conversation_id=key[2],
            timeline=timing, conversation=original, partial_observation=True, normalization=normalization))
    result = []
    for identity_key in sorted(groups):
        group = groups[identity_key]
        if not group['contributions']:
            continue
        group['id'] = len(result) + 1
        group['timeout_normalizations'] = [dict(source_ref=row['source_ref'], capture_session=row['capture_session'],
            conversation_id=row['conversation_id'], **row['normalization']) for row in group['contributions'] if row.get('partial_observation')]
        group['presentation_check'] = check_presentations(group.pop('presentation_trials'))
        conflicts, menus, inputs = [], [], []
        for node in group['nodes']:
            children = list(node['children'].values())
            node['children'] = children
            if node['kind'] == 'menu':
                observed = sorted({group['nodes'][child]['fields']['value'] for child in children
                                   if group['nodes'][child]['kind'] == 'choice'})
                menus.append(dict(node_id=node['id'], total=len(node['fields']['options']), observed=observed,
                                  unobserved=[n for n in range(1, len(node['fields']['options']) + 1) if n not in observed]))
            elif node['kind'] in ('number', 'text'):
                inputs.append(dict(node_id=node['id'], kind=node['kind'], replies=[
                    dict(node_id=child, fields=group['nodes'][child]['fields']) for child in children
                    if group['nodes'][child]['kind'] in ('number_reply', 'text_reply')]))
            elif len(children) > 1:
                conflicts.append(dict(node_id=node['id'], children=children, reason='divergence_without_observed_choice'))
        touch_conversations = [row['conversation'] for row in group['contributions']
                               if is_touch(row['conversation'].get('npc', {}))]
        touch_trials = compare_conversation_trials(
            touch_conversations,
            touch_inferences,
            source_refs={row['conversation']['capture_session']: row['source_ref']
                         for row in group['contributions']})
        group.update(conflicts=conflicts, menus=menus, inputs=inputs,
                     touch_trial_comparison=touch_trials,
                     touch_trial_caption=format_trial_comparison(touch_trials) if touch_trials else '',
                     condition_generation='excluded', server_conditions_restored=False, timers_restored=False)
        result.append(group)
    excluded.sort(key=lambda row: (row['source_ref'], row['capture_session'], row['conversation_id'], row['reason']))
    return dict(schema_version=2, groups=result, excluded=excluded, node_count=node_count,
                input_capacity_reached=input_capacity_reached,
                condition_generation='excluded', server_conditions_restored=False, timers_restored=False)
