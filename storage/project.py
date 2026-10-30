"""Bounded, declarative offline project references. Never stores packet payloads."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from copy import deepcopy
from storage.observation_export import validate_export_destination

FILE_KEYS = {'log', 'definitions', 'recv', 'send', 'dialogue'}
MAX_CONFIG = 2 * 1024 * 1024
CATALOG_PATHS = {key:Path(__file__).resolve().parents[1]/'config'/filename for key,filename in
                 (('skill_names','skill_names.json'),('skill_units','skill_units.json'),
                  ('reference_names','reference_names.json'),('client_names','client_names.json'),('navigation','navigation.json'))}


def config_limit(key):
    return 4*1024*1024 if key=='navigation' else MAX_CONFIG


def fingerprint(path, limit, cancelled=None):
    if not Path(path).is_file():
        raise FileNotFoundError('参照先が通常のファイルではありません。')
    digest, size = hashlib.sha256(), 0
    with Path(path).open('rb') as source:
        while chunk := source.read(1024 * 1024):
            if cancelled and cancelled():
                raise InterruptedError()
            size += len(chunk)
            if size > limit:
                raise ValueError('参照ファイルがサイズ上限を超えています。')
            digest.update(chunk)
    return digest.hexdigest()


def validate_view(view):
    if not isinstance(view, dict) or set(view) != {'filter', 'timestamps', 'unmapped', 'tab', 'conversation', 'merged'}:
        raise ValueError('作業設定の形式が不正です。')
    if (not isinstance(view['filter'], str) or len(view['filter']) > 256
            or any(type(view[key]) is not bool for key in ('timestamps', 'unmapped', 'merged'))
            or type(view['tab']) is not int or not 0 <= view['tab'] <= 5
            or type(view['conversation']) is not int or not -1 <= view['conversation'] < 2000):
        raise ValueError('作業設定の値が不正です。')


def catalog_references(catalogs, destination, expected_hashes=None):
    if catalogs is None:
        return None
    if not isinstance(catalogs,dict) or not catalogs or set(catalogs)-CATALOG_PATHS.keys():
        raise ValueError('名称辞書の参照形式が不正です。')
    references={}
    for key,path in catalogs.items():
        source=Path(path).resolve()
        if source==destination:raise ValueError('名称辞書への上書きはできません。')
        sha=fingerprint(source,config_limit(key))
        if expected_hashes is not None and expected_hashes.get(key)!=sha:
            raise ValueError('使用中の名称辞書が変更されています。再読込してください。')
        references[key]=dict(path=str(source),sha256=sha)
    verify_runtime_catalogs(dict(catalogs=references))
    return references


def verify_runtime_catalogs(document,cancelled=None):
    for key,ref in document.get('catalogs',{}).items():
        if fingerprint(CATALOG_PATHS[key],config_limit(key),cancelled)!=ref['sha256']:
            raise ValueError('現在の名称辞書が保存時と異なります。保存時の同梱辞書を復元してください。')


def save_project(path, files, view, note, expected_log_hash, *, catalogs=None, expected_catalog_hashes=None):
    destination = Path(path).resolve()
    if set(files) != FILE_KEYS or not isinstance(note, str) or len(note) > 8192:
        raise ValueError('プロジェクト設定の形式が不正です。')
    validate_view(view)
    references = {}
    for key, source in files.items():
        source = Path(source).resolve()
        if source == destination:
            raise ValueError('入力ファイルへの上書きはできません。')
        digest = fingerprint(source, 128 * 1024 * 1024 if key == 'log' else config_limit(key))
        if key == 'log' and digest != expected_log_hash:
            raise ValueError('読み戻し後に生ログが変更されています。再読込してください。')
        references[key] = dict(path=str(source), sha256=digest)
    document = dict(schema=1, kind='game-packet-analyzer-project', files=references, view=view, note=note)
    catalog_refs=catalog_references(catalogs,destination,expected_catalog_hashes)
    if catalog_refs is not None:document['catalogs']=catalog_refs
    _write_project(destination, document)


def _write_project(destination, document):
    destination = validate_export_destination(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(document, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def load_project(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('プロジェクトに重複キーがあります。')
            result[key] = value
        return result
    with Path(path).open('rb') as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('プロジェクトファイルがサイズ上限を超えています。')
    try:
        document = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, RecursionError) as exc:
        raise ValueError('プロジェクトJSONの形式が不正です。') from exc
    if not isinstance(document, dict):
        raise ValueError('不正なプロジェクト形式です。')
    schema = document.get('schema')
    expected_keys = ({'schema', 'kind', 'files', 'view', 'note'} | ({'sources'} if schema == 2 else set())
                     | ({'catalogs'} if 'catalogs' in document else set()))
    if (set(document) != expected_keys
            or type(schema) is not int or schema not in (1, 2)
            or document['kind'] != 'game-packet-analyzer-project'
            or not isinstance(document['files'], dict)
            or set(document['files']) != (FILE_KEYS if schema == 1 else FILE_KEYS - {'log', 'definitions'})
            or not isinstance(document['note'], str) or len(document['note']) > 8192):
        raise ValueError('未対応または不正なプロジェクト形式です。')
    validate_view(document['view'])
    if 'catalogs' in document and (not isinstance(document['catalogs'],dict)
            or not document['catalogs'] or set(document['catalogs'])-CATALOG_PATHS.keys()):
        raise ValueError('名称辞書の参照形式が不正です。')
    if schema == 2:
        sources = document['sources']
        if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
            raise ValueError('ログ件数が不正です。')
        sessions = []
        for row in sources:
            if (not isinstance(row, dict) or set(row) != {'log', 'definitions', 'capture_session'}
                    or type(row['capture_session']) is not int or not 1 <= row['capture_session'] <= 20):
                raise ValueError('ログの取得世代が不正です。')
            sessions.append(row['capture_session'])
        if sessions != sorted(set(sessions)):
            raise ValueError('取得世代が重複または逆順です。')
    for key, ref in project_references(document):
        if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}
                or not isinstance(ref['path'], str) or len(ref['path']) > 4096
                or not isinstance(ref['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', ref['sha256'])):
            raise ValueError('参照ファイル情報が不正です。')
        ref['path'] = str((Path(path).resolve().parent / ref['path']).resolve())
    if schema == 2:
        hashes = [row['log']['sha256'] for row in document['sources']]
        if len(set(hashes)) != len(hashes):
            raise ValueError('同じ内容のログが重複しています。')
    return document


def verify_project(document, cancelled=None):
    for key, ref in project_references(document):
        digest = fingerprint(ref['path'], 128 * 1024 * 1024 if key == 'log' else config_limit(key), cancelled)
        if digest != ref['sha256']:
            raise ValueError('参照ファイルが保存時から変更されています。元ファイルを復元するか生ログから開き直してください。')
    verify_runtime_catalogs(document,cancelled)


def project_references(document):
    yield from document['files'].items()
    yield from document.get('catalogs',{}).items()
    for row in document.get('sources', []):
        yield 'log', row['log']
        yield 'definitions', row['definitions']


def save_multiple_project(path, files, sources, view, note, *, catalogs=None, expected_catalog_hashes=None):
    destination = Path(path).resolve()
    validate_view(view)
    if (set(files) != FILE_KEYS - {'log', 'definitions'} or not 1 <= len(sources) <= 20
            or not isinstance(note, str) or len(note) > 8192):
        raise ValueError('複数ログの作業設定が不正です。')
    def reference(source, key, expected=None):
        source = Path(source).resolve()
        if source == destination:
            raise ValueError('入力への上書きはできません。')
        digest = fingerprint(source, 128 * 1024 * 1024 if key == 'log' else config_limit(key))
        if expected is not None and digest != expected:
            raise ValueError('生ログが変更されています。')
        return dict(path=str(source), sha256=digest)
    references = {key: reference(source, key) for key, source in files.items()}
    rows, sessions = [], []
    for source in sources:
        sessions.append(source['capture_session'])
        rows.append(dict(capture_session=source['capture_session'],
                         log=reference(source['source_log'], 'log', source['source_sha256']),
                         definitions=reference(source['definitions_path'], 'definitions')))
    if (any(type(value) is not int or not 1 <= value <= 20 for value in sessions)
            or sessions != sorted(set(sessions))):
        raise ValueError('取得世代が不正です。')
    if len({row['log']['sha256'] for row in rows}) != len(rows):
        raise ValueError('同じ内容のログが重複しています。')
    document=dict(schema=2, kind='game-packet-analyzer-project', files=references, sources=rows, view=view, note=note)
    catalog_refs=catalog_references(catalogs,destination,expected_catalog_hashes)
    if catalog_refs is not None:document['catalogs']=catalog_refs
    _write_project(destination,document)


def relocate_project(document, replacements):
    """Return a new manifest with content-identical references; keep input intact."""
    result = deepcopy(document)
    refs = list(project_references(result))
    for index, path in replacements.items():
        if type(index) is not int or not 0 <= index < len(refs):
            raise ValueError('参照番号が不正です。')
        key, ref = refs[index]
        candidate = Path(path).resolve()
        if fingerprint(candidate, 128 * 1024 * 1024 if key == 'log' else config_limit(key)) != ref['sha256']:
            raise ValueError('選択したファイルが保存時の内容と一致しません。')
        old_path = ref['path']
        for _, shared in refs:
            if shared['path'] == old_path and shared['sha256'] == ref['sha256']:
                shared['path'] = str(candidate)
    return result


def save_relocated_project(destination, document):
    destination = Path(destination).resolve()
    refs = list(project_references(document))
    if any(Path(ref['path']).resolve() == destination for _, ref in refs):
        raise ValueError('入力ファイルへの上書きはできません。')
    if sum(Path(ref['path']).stat().st_size for key, ref in refs if key == 'log') > 128 * 1024 * 1024:
        raise ValueError('ログ合計がGUI再生上限を超えています。')
    verify_project(document)
    _write_project(destination, document)
