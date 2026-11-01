"""Task-local frozen rendering files; regular GUI rendering keeps its normal reads."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
from pathlib import Path

_ACTIVE=ContextVar('npc_render_inputs',default=None)
MAX_PROFILE_BYTES=2*1024*1024


def _bytes(path):
    path=Path(path).absolute()
    frozen=_ACTIVE.get()
    if frozen is None:return path.read_bytes()
    if path not in frozen:raise ValueError('生成時に固定されていない書式ファイルです。')
    value=frozen[path]
    if isinstance(value,Exception):raise value
    return value


def read_render_json(path):return json.loads(_bytes(path).decode('utf-8'))


def render_profile_size(path):
    return len(_bytes(path)) if _ACTIVE.get() is not None else Path(path).stat().st_size


@dataclass(frozen=True)
class NpcRenderInputs:
    files: dict

    @contextmanager
    def activate(self):
        token=_ACTIVE.set(self.files)
        try:yield
        finally:_ACTIVE.reset(token)


def freeze_npc_render_inputs():
    from reconstruction.emulator_profiles import profile
    files={}
    for name in ('dialogue.json', 'shops.json', 'barters.json', 'entity_metadata.json',
                 'status_ids.json', 'identity_protection.json'):
        path=profile(name).absolute()
        try:
            with path.open('rb') as stream:data=stream.read(MAX_PROFILE_BYTES+1)
            files[path]=data if len(data)<=MAX_PROFILE_BYTES else ValueError('生成書式は1ファイル2MiB以内にしてください。')
        except OSError as exc:
            # Keep the previous lazy-loading behavior for an unused missing profile.
            files[path]=exc
    return NpcRenderInputs(files)
