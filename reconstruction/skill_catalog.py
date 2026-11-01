"""Restricted static Lua table import. Never executes Lua or client binaries."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from reconstruction.skills import validate_skill_names

REFERENCE_ROOT = Path(__file__).resolve().parents[1] / '.reference'
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_TOKENS = 300000
LAYOUT = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*")
NUMBER = re.compile(rb"-?\d+(?:\.\d+)?")


def read_bounded(path, limit=MAX_SOURCE_BYTES):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Import input exceeds size limit')
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate dictionary key: {key}')
        result[key] = value
    return result


def tokenize(data, encoding):
    if encoding not in ('cp932', 'utf-8'):
        raise ValueError('Supported encodings: cp932, utf-8')
    if data.startswith(b'\x1bLua'):
        raise ValueError('Lua bytecode is not supported')
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    tokens = []
    i = 0
    escapes = {97:7, 98:8, 102:12, 110:10, 114:13, 116:9, 118:11}
    while i < len(data):
        if data[i] in b' \t\r\n':
            i += 1
            continue
        if data[i:i+2] == b'--':
            start = i + 2
            long = re.match(rb'\[(=*)\[', data[start:])
            if long:
                end = data.find(b']' + long[1] + b']', start + long.end())
                if end < 0:
                    raise ValueError('Unclosed Lua comment')
                i = end + len(long[1]) + 2
            else:
                end = data.find(b'\n', start)
                i = len(data) if end < 0 else end + 1
            continue
        offset = i
        if data[i] in (34, 39):
            quote = data[i]
            i += 1
            value = bytearray()
            while i < len(data) and data[i] != quote:
                char = data[i]
                if char in (10, 13):
                    raise ValueError(f'Unescaped newline in string at {offset}')
                if char != 92:
                    value.append(char)
                    i += 1
                    continue
                i += 1
                if i == len(data):
                    raise ValueError('Unclosed string escape')
                char = data[i]
                if 48 <= char <= 57:
                    end = i
                    while end < len(data) and end < i + 3 and 48 <= data[end] <= 57:
                        end += 1
                    number = int(data[i:end])
                    if number > 255:
                        raise ValueError('Lua byte escape exceeds 255')
                    value.append(number)
                    i = end
                    continue
                if char in (34, 39, 92):
                    value.append(char)
                elif char in escapes:
                    value.append(escapes[char])
                elif char in (10, 13):
                    value.append(10)
                    if char == 13 and data[i+1:i+2] == b'\n':
                        i += 1
                else:
                    raise ValueError(f'Unsupported Lua escape at {i}')
                i += 1
            if i == len(data):
                raise ValueError('Unclosed Lua string')
            i += 1
            tokens.append(('string', bytes(value).decode(encoding, errors='strict')))
        elif data[i] in b'{}[]=,;.':
            tokens.append((chr(data[i]), chr(data[i])))
            i += 1
        else:
            match = NUMBER.match(data, i)
            if match:
                literal = match[0]
                if len(literal) > 32:
                    raise ValueError('Numeric literal too long')
                value = float(literal) if b'.' in literal else int(literal)
                if type(value) is float and not math.isfinite(value):
                    raise ValueError('Nonfinite Lua number')
                tokens.append(('number', value))
            else:
                match = LAYOUT.match(data, i)
                if not match:
                    raise ValueError(f'Unsupported Lua syntax at byte {i}')
                tokens.append(('name', match[0].decode('ascii')))
            i = match.end()
        if len(tokens) > MAX_TOKENS:
            raise ValueError('Lua token limit exceeded')
    tokens.append(('eof', None))
    return tokens


class TableParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    def take(self, kind):
        token = self.tokens[self.index]
        if token[0] != kind:
            raise ValueError(f'Expected {kind}, got {token[0]} at token {self.index}')
        self.index += 1
        return token[1]

    def value(self, depth=0):
        if depth > 48:
            raise ValueError('Lua table nesting limit exceeded')
        kind, value = self.tokens[self.index]
        if kind == '{':
            self.take('{')
            table = {}
            implicit = 1
            while self.tokens[self.index][0] != '}':
                if self.tokens[self.index][0] == '[':
                    self.take('[')
                    key = self.value(depth + 1)
                    self.take(']')
                    self.take('=')
                elif (self.tokens[self.index][0] == 'name'
                      and self.tokens[self.index+1][0] == '='):
                    key = self.take('name')
                    self.take('=')
                else:
                    key = implicit
                    implicit += 1
                if type(key) not in (str, int, tuple):
                    raise ValueError('Unsupported table key')
                if key in table:
                    raise ValueError(f'Duplicate Lua key: {key!r}')
                table[key] = self.value(depth + 1)
                if self.tokens[self.index][0] not in (',', ';'):
                    break
                self.index += 1
            self.take('}')
            return table
        if kind in ('string', 'number'):
            self.index += 1
            return value
        if kind == 'name':
            self.index += 1
            if value in ('true', 'false', 'nil'):
                return {'true':True, 'false':False, 'nil':None}[value]
            # EFST_IDs.EFST_X style refs require a dot; bare COLOR_* names are constants.
            if self.tokens[self.index][0] == '.':
                self.take('.')
                return ('ref', value, self.take('name'))
            return ('name', value)
        raise ValueError(f'Unsupported Lua value at token {self.index}')


def parse_table(data, name, encoding='cp932'):
    parser = TableParser(tokenize(data, encoding))
    if parser.take('name') != name:
        raise ValueError(f'Expected assignment to {name}')
    parser.take('=')
    result = parser.value()
    if type(result) is not dict:
        raise ValueError('Expected root Lua table')
    if parser.tokens[parser.index][0] == ';':
        parser.take(';')
    parser.take('eof')
    return result


def build_import(skillid_path, info_path, dictionary_path, encoding='cp932'):
    paths = [Path(path).resolve() for path in (skillid_path, info_path, dictionary_path)]
    if len(set(paths)) != 3:
        raise ValueError('Inputs must be different files')
    blobs = [read_bounded(path, 1024*1024 if index == 2 else MAX_SOURCE_BYTES)
             for index, path in enumerate(paths)]
    ids = parse_table(blobs[0], 'SKID', encoding)
    info = parse_table(blobs[1], 'SKILL_INFO_LIST', encoding)
    current = json.loads(blobs[2].decode('utf-8'), object_pairs_hook=unique_json_object)
    old_names = validate_skill_names(current)
    source_names, symbols, issues = {}, {}, []
    aliases = {}
    for symbol, value in ids.items():
        if (type(symbol) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', symbol)
                or type(value) is not int or not 0 < value <= 65535):
            raise ValueError('Invalid SKID constant')
        aliases.setdefault(value, []).append(symbol)
    for key, fields in info.items():
        if not isinstance(key, tuple) or key[:2] != ('ref', 'SKID') or type(fields) is not dict:
            raise ValueError('Unsupported skill info record key')
        symbol = key[2]
        skill = ids.get(symbol)
        name = fields.get('SkillName')
        if skill is None:
            issues.append(dict(symbol=symbol, reason='unresolved_skid'))
            continue
        if (not isinstance(name, str) or not name.strip() or len(name) > 256
                or not all(char.isprintable() for char in name)):
            issues.append(dict(symbol=symbol, reason='invalid_name'))
            continue
        if skill in source_names and source_names[skill] != name:
            issues.append(dict(id=skill, symbol=symbol, reason='conflicting_lua_names'))
            continue
        source_names[skill] = name
        symbols.setdefault(skill, []).append(symbol)
    if not source_names:
        issues.append(dict(reason='no_skill_names'))
    additions = [dict(id=key, name=value, symbols=symbols[key])
                 for key, value in sorted(source_names.items()) if key not in old_names]
    changes = [dict(id=key, before=old_names[key], name=value, symbols=symbols[key])
               for key, value in sorted(source_names.items()) if key in old_names and old_names[key] != value]
    references = [dict(path=str(path), sha256=digest(blob)) for path, blob in zip(paths, blobs)]
    updated = dict(current)
    names = dict(old_names)
    names.update(source_names)
    updated['skills'] = {str(key):value for key,value in sorted(names.items())}
    updated['source'] = 'Existing dictionary + client skillinfoz; Lua names take precedence'
    updated['name_resolution'] = dict(policy='lua_wins', catalog_version=1, encoding=encoding,
                                      sources=references[:2])
    validate_skill_names(updated)
    result_hash = digest((json.dumps(updated, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    report = dict(schema_version=1, stage='validated_import_plan', ready=not issues,
        policy='lua_wins', inputs=references, encoding=encoding, issues=issues, result_sha256=result_hash,
        source_name_count=len(source_names), before_count=len(old_names), result_count=len(names),
        additions=additions, changes=changes,
        retained_existing_ids=sorted(set(old_names)-set(source_names)),
        aliases=[dict(id=key,symbols=value) for key,value in sorted(aliases.items()) if len(value)>1])
    return updated, report


def apply_import(document, report):
    if not report['ready']:
        raise ValueError('Import has unresolved or invalid records')
    data = (json.dumps(document, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    if len(data) > 1024*1024:
        raise ValueError('Skill dictionary exceeds 1 MiB')
    validate_skill_names(document)
    if digest(data) != report['result_sha256']:
        raise ValueError('Validated import document changed')
    paths = [Path(row['path']).resolve() for row in report['inputs']]
    destination = paths[2]
    if destination.is_relative_to(REFERENCE_ROOT.resolve()):
        raise ValueError('Reference data is read-only')
    def check_inputs():
        for index, (path, row) in enumerate(zip(paths, report['inputs'])):
            if digest(read_bounded(path, 1024*1024 if index==2 else MAX_SOURCE_BYTES)) != row['sha256']:
                raise ValueError('Import input changed; run dry-run again')
    check_inputs()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        check_inputs()
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return digest(data)
