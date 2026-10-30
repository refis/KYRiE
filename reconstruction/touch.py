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


def context(npc, position, packet_index):
    result = dict(basis=f"class{npc.get('class_id')}_contact_candidate",
                  class_id=npc.get('class_id'), base_class=declaration_class(npc),
                  packet_index=packet_index, radius_x=1, radius_y=1, range_basis='default_3x3',
                  confirmed_axes=dict(x=False, y=False), range_provisional=True, cause_confirmed=False)
    if position and position.get('map_name') == npc.get('map_name'):
        if position.get('position_basis') == 'observed_walk_destination':
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
