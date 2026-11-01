"""Finite rendering projection of observed menu returns; source trees remain unchanged."""
from copy import deepcopy
import json

# Explicit list: new presentation types must be reviewed before treating them as
# straight-line observations. Input prompts and closing boundaries remain barriers.
PASS_THROUGH = {'choice', 'mes', 'next', 'clear', 'cutin', 'emotion', 'effect', 'effect_value', 'effect_remove', 'sound',
                'overhead', 'viewpoint', 'classchange', 'progressbar', 'announcement', 'unittalk', 'colored_speech',
                'event_marker', 'hat_effect'}
PASS_THROUGH.update({'visibility_action', 'status_action', 'progress_action', 'unittalk_target', 'action_wait_review', 'script_command', 'npc_display_action'})
PASS_THROUGH.update({'dialogue_size','dialogue_position','dialogue_alignment'})
PASS_THROUGH.update({'quest_set', 'quest_delete', 'quest_wait_review'})


def share_menu_continuations(nodes, max_actions=100000):
    """Join fully observed equal responses up to their identical next menu."""
    shared, normalized, actions = set(), {}, 0
    def tick():
        nonlocal actions
        actions += 1
        if actions > max_actions:
            raise ValueError('Shared menu projection exceeds action limit')
    for menu in nodes:
        if menu['kind'] != 'menu' or len(menu['fields']['options']) < 2:
            continue
        choices = [nodes[value] for value in menu['children']]
        if (len(choices) != len(menu['fields']['options']) or
                any(choice['kind'] != 'choice' for choice in choices) or
                {choice['fields']['value'] for choice in choices} != set(range(1, len(choices) + 1))):
            continue
        current = choices
        while all(len(node['children']) == 1 for node in current):
            tick()
            current = [nodes[node['children'][0]] for node in current]
            first = current[0]
            if any((node['kind'], node['fields'], node.get('observed_gap')) !=
                   (first['kind'], first['fields'], first.get('observed_gap')) for node in current[1:]):
                break
            if first['kind'] == 'menu':
                # Keep unanswered/pending menus separate; do not turn partial evidence into coverage.
                if any(not node['children'] or any(nodes[c]['kind'] != 'choice' for c in node['children'])
                       for node in current):
                    break
                shared.add(menu['id'])
                normalized.update((choice['id'], 1) for choice in choices)
                break
            if first['kind'] not in PASS_THROUGH - {'choice'}:
                break
    if not shared:
        return nodes
    result = [dict(deepcopy(nodes[0]), children=[])]
    siblings = {}
    pending = [(child, 0) for child in reversed(nodes[0]['children'])]
    while pending:
        tick()
        original, parent = pending.pop()
        source = nodes[original]
        node = dict(deepcopy(source), children=[])
        if original in shared:
            node['shared_response'] = True
        if original in normalized:
            node['fields'] = {'value': normalized[original]}
        key = (parent, node['kind'], json.dumps(node['fields'], sort_keys=True),
               node.get('observed_gap'), node.get('shared_response', False))
        destination = siblings.get(key)
        if destination is None:
            destination = len(result)
            node['id'] = destination
            result.append(node)
            result[parent]['children'].append(destination)
            siblings[key] = destination
        elif isinstance(node.get('evidence'), list):
            result[destination]['evidence'].extend(deepcopy(node['evidence']))
        pending.extend((child, destination) for child in reversed(source['children']))
    return result


def fold_menu_loops(nodes, max_actions=100000):
    """Fold exact ancestor-menu returns without crossing other menus or input prompts."""
    cutins = {0: False}
    for node in nodes:
        current = cutins.get(node['id'], False)
        if node['kind'] == 'cutin':
            current = node['fields']['position'] != 255
        for child in node['children']:
            cutins[child] = current
    result = [dict(deepcopy(nodes[0]), children=[])]
    siblings, seen, actions = {}, set(), 0

    def tick():
        nonlocal actions
        actions += 1
        if actions > max_actions:
            raise ValueError('Menu loop projection exceeds action limit')

    def returns(start):
        def answered(value):
            children = nodes[value]['children']
            return bool(children) and all(nodes[child]['kind'] == 'choice' for child in children)
        if not answered(start):
            return frozenset({start})
        targets, pending = {start}, list(nodes[start]['children'])
        while pending:
            tick()
            value = pending.pop()
            node = nodes[value]
            if node['kind'] == 'menu':
                if (node['fields'] != nodes[start]['fields'] or cutins[value] != cutins[start]
                        or node.get('shared_response', False) != nodes[start].get('shared_response', False)
                        or not answered(value)):
                    continue
                targets.add(value)
            elif node['kind'] not in PASS_THROUGH:
                continue
            pending.extend(node['children'])
        return frozenset(targets)

    pending = [(child, 0, frozenset()) for child in reversed(nodes[0]['children'])]
    while pending:
        tick()
        original, parent, targets = pending.pop()
        identity = (original, parent, targets)
        if identity in seen:
            continue
        seen.add(identity)
        source = nodes[original]
        node = dict(deepcopy(source), children=[])
        loop_targets = frozenset()
        if original in targets:
            node['kind'], node['fields'] = 'loop_continue', {}
        elif source['kind'] == 'menu':
            loop_targets = returns(original)
            if len(loop_targets) > 1:
                node['kind'] = 'loop_menu'
        signature = (parent, node['kind'], json.dumps(node['fields'], sort_keys=True, ensure_ascii=False),
                     node.get('observed_gap'), node.get('shared_response', False))
        destination = siblings.get(signature)
        if destination is None:
            destination = len(result)
            node['id'] = destination
            result.append(node)
            result[parent]['children'].append(destination)
            siblings[signature] = destination
        elif isinstance(node.get('evidence'), list):
            result[destination]['evidence'].extend(deepcopy(node['evidence']))
        if node['kind'] == 'loop_continue':
            continue
        if len(loop_targets) > 1:
            children = [child for target in sorted(loop_targets) for child in nodes[target]['children']]
            pending.extend((child, destination, loop_targets) for child in reversed(children))
        else:
            pending.extend((child, destination, targets) for child in reversed(source['children']))
    return result
