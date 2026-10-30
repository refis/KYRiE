from pathlib import Path
import warnings


def load_lengths(path):
    result = {}
    for lineno, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.split('//', 1)[0].split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.replace(',', ' ').split()
        if len(parts) != 2:
            raise ValueError(f'Line {lineno}: expected hex ID and decimal length')
        pid = int(parts[0].removeprefix('0x'), 16)
        size = int(parts[1], 10)
        if not 0 <= pid <= 65535 or (size != -1 and not 2 <= size <= 65535):
            raise ValueError(f'Line {lineno}: invalid ID or size')
        if pid in result and result[pid] != size:
            warnings.warn(f'Line {lineno}: ID 0x{pid:04X} override {result[pid]} -> {size} (last wins)', stacklevel=2)
        result[pid] = size
    if not result:
        raise ValueError('No packet definitions found')
    return result
