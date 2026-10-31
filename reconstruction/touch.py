"""Contact candidates and independently observed axes; never infer walk completion."""

from reconstruction.actor_appearance import declaration_class

TOUCH_CLASSES = (139, 111, 844, 45)
MAX_TOUCH_RADIUS = 15

def priority(class_id):
    return TOUCH_CLASSES.index(class_id) if class_id in TOUCH_CLASSES else len(TOUCH_CLASSES)


def is_touch(npc):
    touch = npc.get('touch', {})
    observed_class = touch.get('class_id', npc.get('class_id'))
    return (type(observed_class) is int and 0 <= observed_class <= 65535
            and touch.get('basis') == f'class{observed_class}_contact_candidate'
            and touch.get('base_class', declaration_class(npc)) == declaration_class(npc))


def can_trigger(npc):
    options = npc.get('options')
    if options is None:
        options = npc.get('initial_options')
    return options is None or type(options) is int and not options & 6


def signed_offsets(npc, position):
    if not position:
        return None
    values = (position.get('x'), position.get('y'), npc.get('x'), npc.get('y'))
    if not all(type(value) is int and 0 <= value <= 1023 for value in values):
        return None
    return dict(dx=position['x'] - npc['x'], dy=position['y'] - npc['y'])


def context(npc, position, packet_index):
    result = dict(basis=f"class{npc.get('class_id')}_contact_candidate",
                  class_id=npc.get('class_id'), base_class=declaration_class(npc),
                  packet_index=packet_index, radius_x=1, radius_y=1, range_basis='default_3x3',
                  confirmed_axes=dict(x=False, y=False), range_provisional=True, cause_confirmed=False)
    offsets = signed_offsets(npc, position)
    if offsets is not None:
        result['signed_offsets'] = offsets
    if position and position.get('map_name') == npc.get('map_name'):
        if position.get('position_basis') == 'observed_walk_destination':
            # Walk destinations are not arrivals; keep the conservative 3x3 provisional range.
            result.update(range_basis='walk_minimum_3x3', player=dict(position))
            return result
        x, y = position.get('x'), position.get('y')
        if all(type(v) is int and 0 <= v <= 1023 for v in (x, y, npc.get('x'), npc.get('y'))):
            dx, dy = abs(x - npc['x']), abs(y - npc['y'])
            if dx <= MAX_TOUCH_RADIUS and dy <= MAX_TOUCH_RADIUS:
                result.update(radius_x=max(1, dx or dy), radius_y=max(1, dy or dx),
                              confirmed_axes=dict(x=dx > 0, y=dy > 0),
                              range_provisional=not (dx > 0 and dy > 0),
                              range_basis='observed_minimum', player=dict(position))
    return result


def merge_contexts(rows):
    result = dict(rows[0])
    axes, values = {}, {}
    for axis in ('x', 'y'):
        observed = [row['radius_' + axis] for row in rows if row.get('confirmed_axes', {}).get(axis) is True]
        axes[axis] = bool(observed)
        values[axis] = max(observed) if observed else None
    for axis, other in (('x', 'y'), ('y', 'x')):
        result['radius_' + axis] = min(MAX_TOUCH_RADIUS, values[axis] or values[other] or max(row['radius_' + axis] for row in rows))
    result.update(confirmed_axes=axes, range_provisional=not all(axes.values()))
    return result


def compare_trials(entries, inferences=None):
    """Build per-trial contact comparison rows without inventing a larger OnTouch range.

    entries: dicts with source_ref/capture_session/conversation_id/flow_id/npc(/touch).
    inferences: optional touch_warp_inferences rows matched by transfer packet index.
    """
    inferences = list(inferences or [])
    rows = []
    for ordinal, entry in enumerate(entries):
        npc = entry.get('npc') or {}
        touch = entry.get('touch') or npc.get('touch') or {}
        if not is_touch(dict(npc, touch=touch)):
            continue
        player = touch.get('player') or {}
        termination = entry.get('termination') or {}
        transfer_index = termination.get('packet_index')
        matched = None
        for inference in inferences:
            if transfer_index is None or inference.get('packet_index') != transfer_index:
                continue
            if inference.get('capture_session') != entry.get('capture_session'):
                continue
            if inference.get('flow_id') != entry.get('flow_id', npc.get('flow_id')):
                continue
            matched = inference
            break
        offsets = touch.get('signed_offsets') or signed_offsets(npc, player)
        rows.append(dict(
            trial=ordinal + 1,
            source_ref=entry.get('source_ref', ''),
            capture_session=entry.get('capture_session', npc.get('capture_session')),
            conversation_id=entry.get('conversation_id'),
            flow_id=entry.get('flow_id', npc.get('flow_id')),
            map_generation=npc.get('map_generation'),
            actor_id=npc.get('actor_id'),
            npc_map=npc.get('map_name'),
            npc_x=npc.get('x'), npc_y=npc.get('y'),
            player_map=player.get('map_name'),
            player_x=player.get('x'), player_y=player.get('y'),
            position_basis=player.get('position_basis') or (
                'observed_position' if player else 'unobserved'),
            signed_dx=(offsets or {}).get('dx'),
            signed_dy=(offsets or {}).get('dy'),
            radius_x=touch.get('radius_x'), radius_y=touch.get('radius_y'),
            range_basis=touch.get('range_basis'),
            range_provisional=touch.get('range_provisional', True),
            confirmed_axes=dict(touch.get('confirmed_axes') or {}),
            cause_confirmed=bool(touch.get('cause_confirmed')),
            walk_send_packet_index=player.get('walk_send_packet_index'),
            walk_recv_packet_index=player.get('packet_index') if player.get('position_basis') == 'observed_walk_destination' else None,
            position_packet_index=player.get('packet_index'),
            touch_packet_index=touch.get('packet_index'),
            transfer_packet_index=transfer_index,
            transfer_packet_id=termination.get('packet_id'),
            candidate_count=(matched or {}).get('candidate_count'),
            nearest_count=(matched or {}).get('nearest_count'),
            selection_reason=(matched or {}).get('reason'),
            selected_actor_id=(matched or {}).get('selected_actor_id'),
        ))
        if len(rows) >= 64:
            break
    return rows


def format_trial_comparison(rows):
    if not rows:
        return ''
    lines = ['接触試行の比較（半径の自動拡大・OnTouch確定は行いません。暫定半径1は既定の仮値です）:']
    for row in rows:
        axes = row.get('confirmed_axes') or {}
        lines.append(
            f"試行{row['trial']}: NPC({row['npc_x']},{row['npc_y']}) / 観測"
            f"({row['player_x']},{row['player_y']}) basis={row['position_basis']} "
            f"dx={row['signed_dx']} dy={row['signed_dy']} / 半径"
            f"{row['radius_x']}x{row['radius_y']} ({row['range_basis']}"
            f"{'・暫定' if row.get('range_provisional') else ''}) / "
            f"軸確認 x={bool(axes.get('x'))} y={bool(axes.get('y'))}")
        evidence = []
        if row.get('walk_send_packet_index') is not None:
            evidence.append(f"歩行SEND#{row['walk_send_packet_index']}")
        if row.get('walk_recv_packet_index') is not None:
            evidence.append(f"受信歩行#{row['walk_recv_packet_index']}")
        elif row.get('position_packet_index') is not None:
            evidence.append(f"位置#{row['position_packet_index']}")
        if row.get('transfer_packet_index') is not None:
            evidence.append(f"転送#{row['transfer_packet_index']}")
        if row.get('candidate_count') is not None:
            evidence.append(f"候補{row['candidate_count']} / {row.get('selection_reason')}")
        evidence.append(f"出典ses{row.get('capture_session')}/flow={row.get('flow_id')}/mapgen={row.get('map_generation')}")
        lines.append('  根拠: ' + ' / '.join(str(part) for part in evidence if part is not None))
    return '\n'.join(lines)


def conversation_entries(conversations, source_refs=None):
    """Build compare_trials entries from Conversation objects or asdict snapshots."""
    source_refs = source_refs or {}
    entries = []
    for item in conversations:
        npc = getattr(item, 'npc', None)
        if npc is None and isinstance(item, dict):
            npc = item.get('npc') or {}
            capture_session = item.get('capture_session')
            conversation_id = item.get('id')
            flow_id = item.get('flow_id')
            termination = item.get('termination') or {}
        else:
            capture_session = item.capture_session
            conversation_id = item.id
            flow_id = item.flow_id
            termination = item.termination or {}
            npc = npc or {}
        if not is_touch(npc):
            continue
        entries.append(dict(
            source_ref=source_refs.get(capture_session, ''),
            capture_session=capture_session,
            conversation_id=conversation_id,
            flow_id=flow_id,
            npc=npc,
            touch=npc.get('touch'),
            termination=termination,
        ))
        if len(entries) >= 64:
            break
    return entries


def compare_conversation_trials(conversations, inferences=None, source_refs=None):
    return compare_trials(conversation_entries(conversations, source_refs), inferences)
