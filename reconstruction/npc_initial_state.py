"""Initial observed visibility is distinct from the latest NPC option notification."""


def visibility_state(npc):
    value = npc.get('initial_options')
    if value is None:
        return 'unobserved'
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('NPC初回状態のoptionsが不正です。')
    return {0: 'visible', 2: 'hidden', 4: 'cloaked', 6: 'ambiguous'}[value & 6]


def declaration_type(npc, *, walking_script2=True):
    """Auriga: type 6 -> script[(HIDDEN/CLOAKED)], type 12 -> script2[(HIDDEN/CLOAKED)].

    rAthena has no script2 kind, so walking_script2=False keeps script for both.
    HIDDEN/CLOAKED remain option modifiers; they must not select script vs script2.
    """
    state = visibility_state(npc)
    if state == 'ambiguous':
        raise ValueError('NPC初回状態にHIDDENとCLOAKEDの両方を観測。配置状態を手動確認してください。')
    base = 'script2' if walking_script2 and npc.get('actor_type') == 12 else 'script'
    return base + {'visible': '', 'unobserved': '', 'hidden': '(HIDDEN)', 'cloaked': '(CLOAKED)'}[state]
