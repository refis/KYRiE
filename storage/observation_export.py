"""Bounded atomic observation export that never replaces source logs or configuration."""
import json
import os
from pathlib import Path
import tempfile

MAX_EXPORT_BYTES = 64 * 1024 * 1024
CONFIG_ROOT = Path(__file__).resolve().parents[1] / 'config'


def save_observations(path, report, source_paths=()):
    save_observation_chunks(path,observation_json_chunks(report),source_paths)


def save_observation_text(path, text, source_paths=()):
    save_observation_chunks(path,(text,),source_paths)


def save_observation_bytes(path, data, source_paths=()):
    destination = validate_export_destination(path, source_paths)
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError('観測出力は64MiB以内にしてください。')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',
                                         dir=destination.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_export_destination(path, source_paths=()):
    """Shared destination checks, without changing caller-specific size/durability rules."""
    destination = Path(path).resolve()
    protected = {Path(source).resolve() for source in source_paths if source}
    if destination in protected or destination.is_relative_to(CONFIG_ROOT):
        raise ValueError('元ログ・設定ファイルへ上書きできません。')
    return destination


class ExportCancelled(Exception):
    pass


class ExportLimitError(ValueError):
    pass


def save_observation_chunks(path,chunks,source_paths=(),*,cancelled=lambda:False):
    """Stream UTF-8 into a sibling temporary file, then atomically replace.

    Inputs are text fragments, with separators supplied by the caller. Cancellation
    is checked between fragments/encoding blocks and immediately before replace.
    Once os.replace succeeds, the export is complete even if cancellation arrives.
    """
    destination=validate_export_destination(path,source_paths)
    temporary=None
    total=0
    def check_cancelled():
        if cancelled():raise ExportCancelled()
    try:
        check_cancelled()
        with tempfile.NamedTemporaryFile(mode='wb',dir=destination.parent,suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            buffer=bytearray()
            for text in chunks:
                check_cancelled()
                for offset in range(0,len(text),16384):
                    check_cancelled()
                    encoded=text[offset:offset+16384].encode('utf-8')
                    total+=len(encoded)
                    if total>MAX_EXPORT_BYTES:raise ExportLimitError('観測出力は64MiB以内にしてください。')
                    buffer.extend(encoded)
                    if len(buffer)>=65536:
                        stream.write(buffer)
                        buffer.clear()
            check_cancelled()
            if buffer:stream.write(buffer)
        check_cancelled()
        validate_export_destination(destination,source_paths)
        check_cancelled()
        os.replace(temporary,destination)
        return total
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def observation_json_chunks(report):
    encoder=json.JSONEncoder(ensure_ascii=False,indent=2,allow_nan=False)
    parts=[];characters=0
    for part in encoder.iterencode(report):
        parts.append(part);characters+=len(part)
        if characters>=16384:
            yield ''.join(parts)
            parts=[];characters=0
    parts.append('\n')
    yield ''.join(parts)


def report_needs_worker(report):
    """Bounded admission estimate, without constructing a JSON string or size copy."""
    from itertools import chain
    stack=[(iter((report,)),None)];active=set();nodes=0;characters=0
    while stack:
        try:value=next(stack[-1][0])
        except StopIteration:
            _,identity=stack.pop()
            if identity is not None:active.remove(identity)
            continue
        nodes+=1
        if nodes>2000:return True
        if isinstance(value,str):
            characters+=len(value)
            if characters>262144:return True
        elif isinstance(value,(dict,list,tuple)):
            if id(value) in active:return True
            active.add(id(value))
            if len(value)>2000:return True
            iterator=iter(chain.from_iterable(value.items()) if isinstance(value,dict) else value)
            stack.append((iterator,id(value)))
    return False
