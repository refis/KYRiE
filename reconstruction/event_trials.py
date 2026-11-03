"""Manually anchored NPC presentation trials; neither ownership nor timers are inferred."""
from copy import deepcopy
import json
import math
from statistics import median
from reconstruction.comparison_anchors import ANCHOR_KINDS, MAX_COMPARISON_ROWS, anchor_identity
from reconstruction.instance_names import npc_name


def unassigned_in_scope(row, anchor, kinds=('announcement',)):
    if (row.get('kind') not in kinds or row.get('actor_id') is not None
            or row.get('target_observed') is not False
            or (row['capture_session'], row['flow_id']) != (anchor['capture_session'], anchor['flow_id'])):
        return False
    context = row.get('map_context')
    npc = anchor.get('npc', {})
    return context is None or (context.get('map_name') == npc.get('map_name')
                              and context.get('map_generation') == npc.get('map_generation'))


def announcement_in_scope(row, anchor):
    return unassigned_in_scope(row, anchor)


def event_scope(row, mode='presentation'):
    npc = row.get('npc', {})
    if mode == 'map_arrival':
        context = npc if npc.get('map_name') else row.get('map_context') or {}
        return (row['capture_session'], row['flow_id'], context.get('map_name'), context.get('map_generation'))
    return (row['capture_session'], row['flow_id'], row['actor_id'],
            npc.get('map_generation'), npc.get('appearance'))


def event_semantics(row, mode='presentation'):
    """The comparison contract shared by grouping and GUI difference inspection."""
    values = [row['kind'], row['fields']]
    if row.get('comparison_scope')=='dialogue_owner':values.append(row.get('effect_target',{}))
    if mode == 'map_arrival' and row.get('anchor_type') != mode:
        npc = row.get('npc', {})
        target = (dict(name=npc_name(npc.get('name'),npc.get('map_name')),
                       **{key:npc.get(key) for key in ('class_id','x','y','direction')})
                  if npc.get('name') else dict(actor_id=row.get('actor_id'), entity_kind=row.get('entity_kind')))
        values.append(target)
    return values


def _valid_timestamp(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False


def _clock_position(when,previous,anchor_time,window_ms):
    """Keep the comparison clock and diagnostic clock on exactly the same rules."""
    if not _valid_timestamp(when):
        return ('invalid_time' if (previous-anchor_time)*1000<=window_ms else 'outside_window'),None,previous
    delta=(when-anchor_time)*1000
    if when<previous:
        relevant=delta<=window_ms or (previous-anchor_time)*1000<=window_ms
        return ('time_reversed' if relevant else 'outside_window'),delta,previous
    return ('outside_window' if delta>window_ms else None),delta,when


def _unassigned_related(row,anchor,mode):
    if row.get('kind') == 'mapcell':
        # A packet may mention a different map. Require explicit scene evidence
        # as well as exact raw map equality; do not assign a caller NPC.
        if (_context_exclusion(row, mode) is not None or not row.get('map_context') or
                row.get('fields', {}).get('map_name') != anchor.get('npc', {}).get('map_name')):
            return False
    layouts = ('dialogue_size', 'dialogue_position', 'dialogue_alignment')
    if row.get('kind') in layouts:
        if (mode != 'dialogue_start' or _context_exclusion(row, mode) is not None
                or not row.get('map_context')
                or row.get('association_basis') != 'same_flow_active_dialogue_layout'
                or row.get('conversation_start_packet_index') != anchor.get('packet_index')):
            return False
    related=unassigned_in_scope(row,anchor,('announcement','music','mapcell','cutin') + layouts)
    return related and (mode!='map_arrival' or event_scope(row,mode)==event_scope(anchor,mode))


def _context_exclusion(row,mode):
    contexts=('outside_dialogue','during_dialogue') if mode=='dialogue_start' else ('outside_dialogue',)
    if row['context'] in contexts:return None
    return row['context'] if row['context'] in ('input_wait','close_wait','during_dialogue','external_candidate','outside_visibility','review_only','after_close_reply','target_unresolved','target_different_map','target_name_ambiguous') else 'other_context'


def trial_review(report, trial_index, observations=(), max_details=1000):
    """Derived inspection only: leave report, eligibility and timer evidence untouched."""
    if type(max_details) is not int or not 1 <= max_details <= 1000:
        raise ValueError('Invalid review detail limit')
    trial = report['trials'][trial_index]
    reference = next((row for row in report['trials'] if not row['quality_flags']), None)
    mode = report.get('anchor_type', 'presentation')
    differences = []
    left, right = trial['events'], reference['events'] if reference else []
    for index in range(max(len(left),len(right))):
        event = left[index] if index < len(left) else None
        base = right[index] if index < len(right) else None
        if reference is None:
            status = 'no_reference'
        elif event is None:
            status = 'unobserved'
        elif base is None:
            status = 'additional'
        else:
            a, b = event_semantics(event['observation'],mode), event_semantics(base['observation'],mode)
            status = ('target_changed' if a[2:] != b[2:] else 'kind_changed' if a[0] != b[0]
                      else 'content_changed' if a[1] != b[1] else 'same')
        differences.append(dict(event_index=index,status=status,
            packet_index=event['observation']['packet_index'] if event else None,
            reference_packet_index=base['observation']['packet_index'] if base else None))
    counts,excluded={},[]
    anchor=trial['anchor']
    previous=anchor['timestamp']
    accepted=0;limit_reached=False
    def retain(row,reason,delta):
        counts[reason]=counts.get(reason,0)+1
        if len(excluded)<max_details:
            offset=round(delta,3) if delta is not None and _valid_timestamp(delta) else None
            excluded.append(dict(reason=reason,offset_ms=offset,observation={key:deepcopy(row.get(key)) for key in
                ('kind','actor_id','entity_kind','packet_index','capture_session','timestamp','connection','context')},
                npc={key:deepcopy(row.get('npc',{}).get(key)) for key in ('name','map_name','class_id','x','y')}))
            if row.get('comparison_scope')=='dialogue_owner':
                observation=excluded[-1]['observation']
                observation['comparison_scope']='dialogue_owner'
                observation['effect_target']=deepcopy(row.get('effect_target',{}))
                raw=row.get('raw_fields',{})
                target=raw.get('target')
                if raw.get('command')=='dropitem':target=dict(name='床出現位置',map_name=raw['arguments'].get('map_name'))
                if isinstance(target,dict):observation['observed_target']=deepcopy(target)
    for position in range(trial['anchor_index'],len(observations)):
        row=observations[position]
        is_anchor=position==trial['anchor_index']
        if (row.get('capture_session'),row.get('flow_id'))!=(anchor['capture_session'],anchor['flow_id']):continue
        if row.get('anchor_type') and not is_anchor:continue
        boundary=(anchor.get('end_after_packets') is not None and
            row['packet_index']-anchor['packet_index']>=anchor['end_after_packets'])
        related=_unassigned_related(row,anchor,mode)
        same_scope=event_scope(row,mode)==event_scope(anchor,mode) or related
        when=row.get('timestamp')
        if boundary or not same_scope or limit_reached:
            # No clock position is claimed for unlocatable/out-of-window rows.
            if not _valid_timestamp(when):continue
            delta=(when-anchor['timestamp'])*1000
            if not 0<=delta<=report['window_ms']:continue
            if boundary:reason='next_boundary'
            elif not same_scope:
                context=row.get('npc') or row.get('map_context') or {}
                origin=anchor.get('npc',{})
                reason=('different_map' if any(context.get(key)!=origin.get(key) for key in ('map_name','map_generation'))
                        else 'different_target')
            else:reason='event_limit'
            retain(row,reason,delta)
            continue
        reason,delta,previous=_clock_position(when,previous,anchor['timestamp'],report['window_ms'])
        if reason=='outside_window':continue
        if reason is None and not is_anchor and not related:reason=_context_exclusion(row,mode)
        if reason is None:
            if accepted<1000:
                accepted+=1
                continue
            reason='event_limit';limit_reached=True
        retain(row,reason,delta)
    return dict(differences=differences,excluded=excluded,excluded_counts=counts,
                omitted_details=sum(counts.values())-len(excluded),reference_available=reference is not None)


def compare_event_trials(observations, anchors, *, window_ms=5000, source_sessions=None):
    if type(window_ms) is not int or not 1 <= window_ms <= 60000:
        raise ValueError('観測窓は1〜60000msで指定してください。')
    if not 2 <= len(anchors) <= 20 or len(set(anchors)) != len(anchors):
        raise ValueError('重複しない基準点を2〜20件選択してください。')
    limit = MAX_COMPARISON_ROWS if any(row.get('anchor_type') in ANCHOR_KINDS for row in observations) else 10000
    if len(observations) > limit:
        raise ValueError('比較観測が保持上限を超えています。')
    if any(type(index) is not int or not 0 <= index < len(observations) for index in anchors):
        raise ValueError('基準点が演出一覧の範囲外です。')
    mode = observations[anchors[0]].get('anchor_type', 'presentation')
    def placement(row):
        return anchor_identity(row)
    def scope(row):
        return event_scope(row, mode)
    def signature(row):
        return json.dumps(event_semantics(row, mode), sort_keys=True, ensure_ascii=False)
    timestamp=_valid_timestamp
    first = observations[anchors[0]]
    identity, anchor_signature = placement(first), signature(first)
    for index in anchors:
        row = observations[index]
        expected_context = 'comparison_anchor' if mode in ANCHOR_KINDS else 'outside_dialogue'
        if row.get('anchor_type', 'presentation') != mode or row['context'] != expected_context or not timestamp(row['timestamp']):
            raise ValueError('基準点には時刻が有効な会話外演出を選択してください。')
        current_identity=placement(row)
        if current_identity!=identity:
            if 'ambiguous_instance_scope' in identity or 'ambiguous_instance_scope' in current_identity:
                raise ValueError('インスタンスNPC名に省略の可能性があるため、別取得・接続・実行時MAP・ActorIDの基準点を同一視できません。')
            raise ValueError('同じNPC配置・同じ演出内容の基準点を選択してください。')
        if signature(row)!=anchor_signature:
            raise ValueError('同じNPC配置・同じ演出内容の基準点を選択してください。')
    trials = []
    for index in anchors:
        anchor = observations[index]
        flags, events, excluded = set(), [], 0
        previous = anchor['timestamp']
        for row in observations[index:]:
            if row.get('anchor_type') and row is not anchor:
                continue
            if (anchor.get('end_after_packets') is not None
                    and row['packet_index'] - anchor['packet_index'] >= anchor['end_after_packets']):
                continue
            unassigned_related = _unassigned_related(row,anchor,mode)
            if scope(row) != scope(anchor) and not unassigned_related:
                continue
            reason,delta,previous=_clock_position(row['timestamp'],previous,anchor['timestamp'],window_ms)
            if reason in ('invalid_time','time_reversed'):
                flags.add('invalid_time')
                continue
            if reason=='outside_window':continue
            if row is not anchor and _context_exclusion(row,mode) is not None and not unassigned_related:
                excluded+=1
                continue
            if len(events) >= 1000:
                flags.add('event_limit')
                break
            events.append(dict(offset_ms=round(delta, 3), observation=deepcopy(row)))
            if unassigned_related:
                events[-1]['association_basis'] = 'selected_timer_window_same_flow'
            if ' [ASSUMED=' in row.get('connection', ''):
                flags.add('assumed_boundary')
        for other in anchors:
            if other != index and scope(observations[other]) == scope(anchor):
                if abs(observations[other]['timestamp'] - anchor['timestamp']) * 1000 <= window_ms:
                    flags.add('overlapping_windows')
        trials.append(dict(anchor_index=index, anchor=deepcopy(anchor), events=events,
                           excluded_input_or_parallel=excluded, quality_flags=sorted(flags),
                           coverage_verified=False, cause_confirmed=False))
    buckets = {}
    for number, trial in enumerate(trials):
        if trial['quality_flags']:
            continue
        key = tuple(signature(event['observation']) for event in trial['events'])
        buckets.setdefault(key, []).append(number)
    variants = []
    for members in buckets.values():
        timings = []
        for position in range(1, len(trials[members[0]]['events'])):
            values = [trials[member]['events'][position]['offset_ms'] for member in members]
            center = median(values)
            spread = round(max(values) - min(values), 3)
            timings.append(dict(event_index=position, min_ms=min(values), median_ms=center,
                                max_ms=max(values), spread_ms=spread,
                                observed_consistent=spread <= max(20, center * .05)))
        status = ('no_followup_observed' if len(trials[members[0]]['events']) <= 1 else
                  'insufficient_repeats' if len(members) < 3 else
                  'repeated_consistent' if all(row['observed_consistent'] for row in timings)
                  else 'repeated_variable')
        variants.append(dict(trial_indices=members, count=len(members), timings=timings, status=status))
    status = ('observed_difference' if len(variants) > 1 else variants[0]['status'] if variants else 'no_eligible_trials')
    result = dict(schema_version=1, npc_identity=identity, window_ms=window_ms, trials=trials, variants=variants,
                status=status, source_sessions=deepcopy(source_sessions or {}),
                transport_quality='not_verified', coverage_verified=False, cause_confirmed=False,
                server_timer_confirmed=False)

    if mode in ANCHOR_KINDS:
        result['anchor_type'] = mode
    return result
