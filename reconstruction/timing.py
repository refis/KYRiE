"""Evidence-based dialogue intervals; capture timestamps are not server timers."""
from copy import deepcopy
from reconstruction.speech_origin import linked_player_notifications
import hashlib
import json
import math
from statistics import median

PROMPTS = {'next', 'menu', 'number', 'text', 'close'}
REPLIES = {'continue': 'next', 'choice': 'menu', 'number_reply': 'number',
           'text_reply': 'text', 'dismiss': 'close'}
BAD_STATUS = {'decode_error', 'capacity_reached', 'interrupted', 'capture_changed', 'past_capture'}


def _milliseconds(start, end):
    if not (isinstance(start, (float, int)) and isinstance(end, (float, int))
            and math.isfinite(start) and math.isfinite(end)):
        return None
    value = (end - start) * 1000
    return round(value, 3) if math.isfinite(value) and value >= 0 else None


def npc_identity(conversation):
    names = ('map_name', 'name', 'class_id', 'x', 'y')
    npc = conversation.npc
    if not npc.get('map_name') or not npc.get('name') or any(npc.get(name) is None for name in names):
        return None
    return {name: npc[name] for name in names}


def build_timeline(conversation, source_ref='', min_gap_ms=100, *, player_notifications=None):
    """Classify adjacent observations and full prompt/reply spans independently."""
    if not math.isfinite(min_gap_ms) or min_gap_ms < 0:
        raise ValueError('min_gap_ms must be finite and nonnegative')
    steps = list(conversation.steps)
    if conversation.termination:
        steps.append(dict(conversation.termination,
                          kind=('shop_opened' if conversation.status == 'shop_opened' else
                                'barter_opened' if conversation.status == 'barter_opened' else 'map_changed'),
                          fields={}))
    rows, waits, gaps = [], [], []
    quality = set()
    if not conversation.observed_open:
        quality.add('start_unobserved')
    if conversation.status in BAD_STATUS:
        quality.add('incomplete_context')
    if conversation.issues:
        quality.add('dialogue_issue')
    pending = None
    path = hashlib.sha256()
    for i, step in enumerate(steps):
        kind = step['kind']
        timestamp = step['timestamp']
        elapsed = _milliseconds(conversation.started, timestamp)
        delta = _milliseconds(steps[i - 1]['timestamp'], timestamp) if i else None
        flags = []
        if elapsed is None or (i and delta is None):
            flags.append('invalid_time')
            quality.add('invalid_time')
        if ' [ASSUMED=' in step.get('connection', ''):
            quality.add('assumed_boundary')
        unanswered_termination = (kind == 'close' and step.get('direction') == 'RECV'
            and step.get('timeout_suspected') is True and pending is not None
            and step.get('timeout_prompt_step_index') == pending
            and step.get('timeout_prompt_kind') == steps[pending]['kind']
            and 'reply' not in steps[pending])
        if unanswered_termination:
            prompt = steps[pending]
            waits.append(dict(prompt_step=pending, reply_step=None,
                prompt_packet_index=prompt['packet_index'], reply_packet_index=None,
                prompt_kind=prompt['kind'], duration_ms=None, complete=False,
                observed_until_ms=_milliseconds(prompt['timestamp'], timestamp),
                termination_step=i, termination_packet_index=step['packet_index'],
                termination_reason='server_close_without_reply', timeout_suspected=True))
            quality.add('unanswered_termination')
            flags.append('unanswered_termination')
            pending = None
        valid_reply = False
        if kind in REPLIES:
            valid_reply = (pending is not None and steps[pending]['kind'] == REPLIES[kind]
                           and (kind == 'dismiss' or step.get('reply_to') == pending))
            if valid_reply:
                prompt = steps[pending]
                waits.append(dict(prompt_step=pending, reply_step=i,
                                  prompt_packet_index=prompt['packet_index'], reply_packet_index=step['packet_index'],
                                  prompt_kind=prompt['kind'], duration_ms=_milliseconds(prompt['timestamp'], timestamp),
                                  complete=True))
            else:
                quality.add('unmatched_reply')
                flags.append('unmatched_reply')
        if not i:
            interval = 'anchor'
        elif delta is None:
            interval = 'invalid_time'
        elif unanswered_termination:
            interval = 'unanswered_termination'
        elif valid_reply:
            interval = 'input_wait'
        elif pending is not None:
            interval = 'during_input_wait'
        elif kind in ('map_changed', 'post_close_warp'):
            interval = 'boundary'
        elif step['direction'] == 'RECV' and steps[i - 1]['direction'] == 'SEND':
            previous = steps[i - 1]
            interval = ('response_latency' if previous['kind'] == 'open' or 'reply_to' in previous
                        else 'ambiguous')
        elif step['direction'] == steps[i - 1]['direction'] == 'RECV':
            interval = 'autonomous_gap'
        else:
            interval = 'ambiguous'
        if interval == 'ambiguous':
            quality.add('ambiguous_interval')
        # All semantic fields, including previous selections/inputs, constrain comparisons.
        path.update(json.dumps([kind, step.get('fields', {})], ensure_ascii=False,
                               sort_keys=True, separators=(',', ':')).encode('utf-8'))
        row = dict(step_index=i, packet_index=step['packet_index'], packet_id=step['packet_id'],
                   timestamp=timestamp, elapsed_ms=elapsed, delta_ms=delta, direction=step['direction'],
                   kind=kind, interval=interval, flags=flags, candidate=False,
                   wait_duration_ms=waits[-1]['duration_ms'] if valid_reply else None)
        rows.append(row)
        if interval == 'autonomous_gap' and delta >= min_gap_ms:
            gaps.append(dict(from_step=i - 1, to_step=i, from_packet_index=steps[i - 1]['packet_index'],
                             to_packet_index=step['packet_index'], duration_ms=delta, path_hash=path.hexdigest()))
        if valid_reply:
            pending = None
        if kind in PROMPTS:
            if pending is not None:
                quality.add('overlapping_prompt')
            pending = i
    if pending is not None:
        prompt = steps[pending]
        waits.append(dict(prompt_step=pending, reply_step=None, prompt_packet_index=prompt['packet_index'],
                          reply_packet_index=None, prompt_kind=prompt['kind'], duration_ms=None,
                          observed_until_ms=_milliseconds(prompt['timestamp'], steps[-1]['timestamp']), complete=False))
    parallel_rows = []
    for record in conversation.parallel_presentations:
        elapsed = _milliseconds(conversation.started, record['timestamp'])
        flags = [] if elapsed is not None else ['invalid_time']
        if flags:
            quality.add('invalid_time')
        parallel_rows.append(dict(step_index=None, prompt_step_index=record['prompt_step_index'],
            packet_index=record['packet_index'], packet_id=record['packet_id'], timestamp=record['timestamp'],
            elapsed_ms=elapsed, delta_ms=None, direction=record['direction'], kind=record['kind'],
            interval='during_input_wait', flags=flags, candidate=False, wait_duration_ms=None,
            track='parallel_presentation'))
    for record in conversation.actions:
        elapsed = _milliseconds(conversation.started, record['timestamp'])
        parallel_rows.append(dict(step_index=None, packet_index=record['packet_index'],
            packet_id=record['packet_id'], timestamp=record['timestamp'], elapsed_ms=elapsed, delta_ms=None,
            direction=record['direction'], kind=record['kind'], interval='observation_only',
            flags=['cause_unconfirmed'], candidate=False, wait_duration_ms=None, track='conversation_action'))
    for record in conversation.resource_observations:
        if record['kind'] == 'map':
            continue  # Already represented by the map boundary row.
        elapsed = _milliseconds(conversation.started, record['timestamp'])
        parallel_rows.append(dict(step_index=None, packet_index=record['packet_index'],
            packet_id=record['packet_id'], timestamp=record['timestamp'], elapsed_ms=elapsed,
            delta_ms=None, direction=record['direction'], kind='resource_' + record['kind'],
            interval='observation_only', flags=['cause_unconfirmed'], candidate=False,
            wait_duration_ms=None, track='resource_observation'))
        if elapsed is None:
            quality.add('invalid_time')
    for record in conversation.late_replies:
        elapsed = _milliseconds(conversation.started, record['timestamp'])
        parallel_rows.append(dict(step_index=None, packet_index=record['packet_index'], packet_id=record['packet_id'],
            timestamp=record['timestamp'], elapsed_ms=elapsed, delta_ms=None, direction=record['direction'], kind=record['kind'],
            interval='observation_only', flags=['late_reply_after_server_close'], candidate=False,
            wait_duration_ms=None, track='late_reply_observation'))
        if elapsed is None:
            quality.add('invalid_time')
    # Conservative: a problem anywhere in a path disqualifies it for repeat statistics.
    candidates = [] if quality else gaps
    for gap in candidates:
        rows[gap['to_step']]['candidate'] = True
    rows.extend(parallel_rows)
    rows.sort(key=lambda row: row['packet_index'])
    if parallel_rows:
        for i, row in enumerate(rows):
            row['delta_ms'] = _milliseconds(rows[i - 1]['timestamp'], row['timestamp']) if i else None
    associated = linked_player_notifications(conversation, player_notifications or {})
    for record in associated[:1000]:
        elapsed = _milliseconds(conversation.started,record['timestamp'])
        rows.append(dict(step_index=None,packet_index=record['packet_index'],packet_id=record['packet_id'],
            timestamp=record['timestamp'],elapsed_ms=elapsed,delta_ms=None,direction=record['direction'],
            kind=record['kind'],interval='observation_only',flags=['cause_unconfirmed']+(['invalid_time'] if elapsed is None else []),
            candidate=False,wait_duration_ms=None,track='player_notification',
            actor_id=record['actor_id'],conversation_actor_id=conversation.actor_id,
            context=record['context'],fields=deepcopy(record['fields']),cause_confirmed=False))
    if associated:
        rows.sort(key=lambda row:row['packet_index'])
    return dict(schema_version=1, source_ref=source_ref, conversation_id=conversation.id,
                capture_session=conversation.capture_session, flow_id=conversation.flow_id,
                actor_id=conversation.actor_id, status=conversation.status, npc_identity=npc_identity(conversation),
                rows=rows, waits=waits, candidates=candidates, quality_flags=sorted(quality),
                player_notification_count=len(associated), player_notification_omitted=max(0,len(associated)-1000),
                excluded_gaps=[dict(gap, reasons=sorted(quality)) for gap in gaps] if quality else [],
                transport_quality='not_verified', min_gap_ms=min_gap_ms,
                timing_basis='packet_delivery_timestamp', server_timer_confirmed=False)


def summarize_timings(timelines, minimum_repeats=3, absolute_tolerance_ms=20, relative_tolerance=0.05):
    """Compare identical observed prefixes at identified NPC placements only."""
    if (not isinstance(minimum_repeats, int) or minimum_repeats < 2
            or not math.isfinite(absolute_tolerance_ms) or absolute_tolerance_ms < 0
            or not math.isfinite(relative_tolerance) or relative_tolerance < 0):
        raise ValueError('Invalid timing comparison policy')
    groups = {}
    unidentified = 0
    for timeline in timelines:
        identity = timeline['npc_identity']
        if identity is None:
            unidentified += len(timeline['candidates'])
            continue
        for gap in timeline['candidates']:
            key = (json.dumps(identity, sort_keys=True, ensure_ascii=False), gap['path_hash'])
            group = groups.setdefault(key, dict(npc_identity=identity, path_hash=gap['path_hash'], samples={}))
            observation = (timeline['source_ref'], timeline['capture_session'], timeline['conversation_id'])
            group['samples'][observation] = dict(source_ref=timeline['source_ref'],
                capture_session=timeline['capture_session'], conversation_id=timeline['conversation_id'],
                flow_id=timeline['flow_id'], **gap)
    results = []
    for key in sorted(groups):
        group = groups[key]
        samples = list(group['samples'].values())
        durations = [sample['duration_ms'] for sample in samples]
        center = median(durations)
        spread = max(durations) - min(durations)
        status = ('insufficient_repeats' if len(samples) < minimum_repeats else
                  'repeated_consistent' if spread <= max(absolute_tolerance_ms, center * relative_tolerance)
                  else 'repeated_variable')
        results.append(dict(npc_identity=group['npc_identity'], path_hash=group['path_hash'],
                            count=len(samples), min_ms=min(durations), median_ms=center, max_ms=max(durations),
                            spread_ms=round(spread, 3), status=status, samples=samples,
                            server_timer_confirmed=False))
    return dict(schema_version=1, groups=results, unidentified_candidates=unidentified,
                minimum_repeats=minimum_repeats, absolute_tolerance_ms=absolute_tolerance_ms,
                relative_tolerance=relative_tolerance, server_timer_confirmed=False)
