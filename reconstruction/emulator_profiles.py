"""Active emulator generation-profile root. Display/send stay on their own loaders."""
from pathlib import Path

CONFIG_ROOT = Path(__file__).resolve().parents[1] / 'config'
TARGETS = frozenset({'auriga', 'rathena'})
_ACTIVE = 'auriga'


def target():
    return _ACTIVE


def set_target(name):
    global _ACTIVE
    if name not in TARGETS:
        raise ValueError(f'Unsupported emulator target: {name}')
    _ACTIVE = name
    return _ACTIVE


def profile(filename, target_name=None):
    name = target_name or _ACTIVE
    if name not in TARGETS:
        raise ValueError(f'Unsupported emulator target: {name}')
    if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError('Invalid generation profile name')
    return CONFIG_ROOT / name / filename


def target_for_path(path):
    # Avoid Path.resolve(): frozen NPC renders patch late resolve() as I/O.
    path = Path(path)
    parts = path.parts
    try:
        index = parts.index('config')
    except ValueError:
        index = -1
    if index >= 0 and index + 1 < len(parts) and parts[index + 1] in TARGETS:
        return parts[index + 1]
    if path.parent.name in TARGETS:
        return path.parent.name
    return None
