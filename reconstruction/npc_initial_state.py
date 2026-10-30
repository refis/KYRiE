"""Initial observed visibility is distinct from the latest NPC option notification."""


def visibility_state(npc):
    value = npc.get('initial_options')
    if value is None:
        return 'unobserved'
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('NPC初回状態のoptionsが不正です。')
    return {0: 'visible', 2: 'hidden', 4: 'cloaked', 6: 'ambiguous'}[value & 6]
