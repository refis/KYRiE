"""Shared --emulator flag for analysis CLIs that load generation profiles."""
from reconstruction.emulator_profiles import TARGETS, set_target, target


def add_emulator_argument(parser):
    parser.add_argument(
        '--emulator', choices=sorted(TARGETS), default='auriga',
        help='Generation profile root under config/ (default: auriga)')


def apply_emulator(name):
    """Activate the generation profile target for this process."""
    return set_target(name)


def active_emulator():
    return target()
