"""Restore manual anchors by log content and observed event identity, never global row numbers."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from reconstruction.event_trials import compare_event_trials
from reconstruction.comparison_anchors import MAX_COMPARISON_ROWS
from storage.project import fingerprint

MAX_SELECTION = 65536
MAX_LOG_BYTES = 128 * 1024 * 1024


def _settings(value):
    if (not isinstance(value, dict) or set(value) != {'mode', 'include_actions'}
            or value['mode'] not in ('presentation', 'dialogue_start', 'map_arrival')
            or type(value['include_actions']) is not bool
            or (value['include_actions'] and value['mode'] != 'dialogue_start')):
        raise ValueError('比較モード・会話アクション設定が不正です。')
    return dict(value)


def _event_hash(row):
    normalized = {key: value for key, value in row.items() if key not in ('capture_session', 'packet_index')}
    if isinstance(normalized.get('speech_origin'), dict):
        normalized['speech_origin'] = {key: value for key, value in normalized['speech_origin'].items()
                                       if key != 'send_packet_index'}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=True,
                                     allow_nan=False).encode('ascii')).hexdigest()


def _observation_hash(observations, hashes, session):
    value = ''.join(hashes[index] for index, row in enumerate(observations) if row['capture_session'] == session)
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _log_identity(path, budget):
    path = Path(path).resolve()
    before = path.stat()
    if not 0 < before.st_size <= budget:
        raise ValueError('参照ログの合計は128MiB以内にしてください。')
    with path.open('rb') as stream:
        header = stream.readline(65537)
    if len(header) > 65536:
        raise ValueError('ログの先頭行が長すぎます。')
    try:
        first = json.loads(header.decode('utf-8'))
    except RecursionError as exc:
        raise ValueError('ログの先頭行の構造が不正です。') from exc
    if (not isinstance(first, dict) or first.get('kind') != 'session_start' or
            type(first.get('schema')) is not int or first.get('schema') != 1 or first.get('record_payload') is not True):
        raise ValueError('基準点の保存・再開には生バイト記録済みログが必要です。')
    digest = fingerprint(path, budget)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('ログが更新されています。取得停止後にやり直してください。')
    return dict(path=str(path), size=after.st_size, sha256=digest)


def _reference(sources, session):
    value = sources.get(session) or sources.get(str(session))
    if not value:
        raise ValueError('基準点の出典ログがありません。ログを読み戻してから操作してください。')
    return value


def build_selection(observations, anchors, source_sessions, window_ms, *, settings=None):
    if settings is not None:
        settings = _settings(settings)
    compare_event_trials(observations, anchors, window_ms=window_ms)
    hashes = [_event_hash(row) for row in observations]
    sources, sessions, entries, budget = [], {}, [], MAX_LOG_BYTES
    for index in anchors:
        row = observations[index]
        session = row['capture_session']
        if session not in sessions:
            source = _log_identity(_reference(source_sessions, session), budget)
            source['observations_sha256'] = _observation_hash(observations, hashes, session)
            if any((item['sha256'], item['size']) == (source['sha256'], source['size']) for item in sources):
                raise ValueError('同じログ内容が複数の取得世代にあります。重複ログを除いてください。')
            sessions[session] = len(sources)
            sources.append(source)
            budget -= source['size']
        digest = hashes[index]
        occurrence = sum(observations[other]['capture_session'] == session and hashes[other] == digest
                         for other in range(index))
        entries.append(dict(source=sessions[session], event_sha256=digest, occurrence=occurrence))
    document = dict(schema_version=1, kind='event_trial_selection', window_ms=window_ms,
                    sources=sources, anchors=entries)
    if settings is not None:
        document.update(schema_version=2, comparison=settings)
    return document


def save_selection(path, observations, anchors, source_sessions, window_ms, *, settings=None):
    destination = Path(path).resolve()
    if destination in {Path(ref).resolve() for ref in source_sessions.values() if ref}:
        raise ValueError('元ログへ上書きできません。')
    document = build_selection(observations, anchors, source_sessions, window_ms, settings=settings)
    text = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    if len(text.encode('utf-8')) > MAX_SELECTION:
        raise ValueError('基準点設定が64KiBを超えています。')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         delete=False, suffix='.tmp') as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_selection(path, observations, source_sessions, *, return_settings=False):
    """A row factory receives validated settings (None for legacy files), before UI changes."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('基準点設定に重複キーがあります。')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('基準点設定に非有限数があります。')
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_SELECTION + 1)
    if len(raw) > MAX_SELECTION:
        raise ValueError('基準点設定が64KiBを超えています。')
    try:
        doc = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('基準点設定の文字コードまたは構造が不正です。') from exc
    if (not isinstance(doc, dict) or set(doc) != ({'schema_version', 'kind', 'window_ms', 'sources', 'anchors'} |
                                      ({'comparison'} if doc.get('schema_version') == 2 else set()))
            or type(doc['schema_version']) is not int or doc['schema_version'] not in (1, 2)
            or doc['kind'] != 'event_trial_selection' or type(doc['window_ms']) is not int
            or not 1 <= doc['window_ms'] <= 60000 or not isinstance(doc['sources'], list)
            or not 1 <= len(doc['sources']) <= 20 or not isinstance(doc['anchors'], list)
            or not 2 <= len(doc['anchors']) <= 20):
        raise ValueError('対応する基準点設定ではありません。')
    settings = _settings(doc['comparison']) if doc['schema_version'] == 2 else None
    def digest(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    for source in doc['sources']:
        if (not isinstance(source, dict) or set(source) != {'path', 'size', 'sha256', 'observations_sha256'}
                or not isinstance(source['path'], str) or len(source['path']) > 4096
                or type(source['size']) is not int or not 0 < source['size'] <= MAX_LOG_BYTES
                or not digest(source['sha256']) or not digest(source['observations_sha256'])):
            raise ValueError('ログ識別情報が不正です。')
    if sum(source['size'] for source in doc['sources']) > MAX_LOG_BYTES:
        raise ValueError('参照ログの合計は128MiB以内にしてください。')
    if len({(source['sha256'], source['size']) for source in doc['sources']}) != len(doc['sources']):
        raise ValueError('基準点設定に同じログ内容が重複しています。')
    for anchor in doc['anchors']:
        if (not isinstance(anchor, dict) or set(anchor) != {'source', 'event_sha256', 'occurrence'}
                or type(anchor['source']) is not int or not 0 <= anchor['source'] < len(doc['sources'])
                or not digest(anchor['event_sha256']) or type(anchor['occurrence']) is not int
                or not 0 <= anchor['occurrence'] < MAX_COMPARISON_ROWS):
            raise ValueError('基準点の識別情報が不正です。')
    if {anchor['source'] for anchor in doc['anchors']} != set(range(len(doc['sources']))):
        raise ValueError('未使用の出典ログが含まれています。')
    if callable(observations):
        observations = observations(settings)
    if len(observations) > MAX_COMPARISON_ROWS:
        raise ValueError('演出観測が10000件を超えています。')
    hashes = [_event_hash(row) for row in observations]
    current, budget = {}, MAX_LOG_BYTES
    for session in dict.fromkeys(row['capture_session'] for row in observations):
        if len(current) >= 20:
            raise ValueError('読込中の出典ログが20件を超えています。')
        current[session] = _log_identity(_reference(source_sessions, session), budget)
        current[session]['observations_sha256'] = _observation_hash(observations, hashes, session)
        budget -= current[session]['size']
    mapping = {}
    for number, source in enumerate(doc['sources']):
        matches = [session for session, item in current.items()
                   if (item['sha256'], item['size'], item['observations_sha256']) ==
                      (source['sha256'], source['size'], source['observations_sha256'])]
        if len(matches) != 1:
            raise ValueError('ログと演出観測を一意に照合できません。読込内容・定義の変更・重複を確認してください。')
        mapping[number] = matches[0]
    indices = []
    for anchor in doc['anchors']:
        matches = [index for index, row in enumerate(observations)
                   if row['capture_session'] == mapping[anchor['source']] and hashes[index] == anchor['event_sha256']]
        if anchor['occurrence'] >= len(matches):
            raise ValueError('基準演出が一致しません。定義・デコード・観測内容の変更を確認してください。')
        indices.append(matches[anchor['occurrence']])
    compare_event_trials(observations, indices, window_ms=doc['window_ms'])
    if return_settings:
        return indices, doc['window_ms'], settings
    return indices, doc['window_ms']
