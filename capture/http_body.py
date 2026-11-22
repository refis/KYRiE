"""Extract field names from bounded HTTP bodies without publishing values."""
from email import policy
from email.parser import BytesParser
import json
import re


class HttpBody:
    MAX_HEADERS = 65536
    MAX_BODY = 256 * 1024
    NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}')

    def __init__(self, *, allow_generic_json=False):
        self.buffer = bytearray()
        self.headers = None
        self.length = 0
        self.done = False
        self.chunked = False
        self.chunk_length = None
        self.decoded = bytearray()
        self.allow_generic_json = allow_generic_json

    @classmethod
    def names(cls, items):
        return sorted({name for name in items if cls.NAME.fullmatch(name)})[:128]

    @classmethod
    def json_keys(cls, body):
        result = cls.json_summary(body)
        return None if result is None else result['json_keys']

    @classmethod
    def json_summary(cls, body):
        try:
            data = json.loads(body)
        except (ValueError, RecursionError):
            return None
        paths = set()

        def visit(value, prefix='', depth=0):
            if depth >= 6 or len(paths) >= 128:
                return
            if isinstance(value, dict):
                for key in cls.names(value):
                    path = f'{prefix}.{key}' if prefix else key
                    paths.add(path)
                    visit(value[key], path, depth + 1)
                    if len(paths) >= 128:
                        break
            elif isinstance(value, list):
                for item in value[:128]:
                    visit(item, prefix + '[]' if prefix else '[]', depth + 1)
            elif isinstance(value, str) and prefix == 'data' and value.lstrip().startswith(('{', '[')):
                try:
                    visit(json.loads(value), prefix, depth + 1)
                except (ValueError, RecursionError):
                    pass

        visit(data)
        summary = dict(json_keys=sorted(paths))
        response_type = data.get('Type') if isinstance(data, dict) else None
        if type(response_type) is int and -(2 ** 31) <= response_type < 2 ** 31:
            summary['response_type'] = response_type
        if isinstance(data, dict):
            page_count = data.get('totalPage')
            if type(page_count) is int and 0 <= page_count < 2 ** 31:
                summary['total_page'] = page_count
            payload = data.get('data')
            if 'data' not in data:
                summary['data_state'] = 'missing'
            elif payload is None:
                summary['data_state'] = 'null'
            elif isinstance(payload, list):
                summary.update(data_state='array', data_count=len(payload))
            elif isinstance(payload, dict):
                summary['data_state'] = 'object'
            else:
                summary['data_state'] = 'scalar'
        return summary

    def feed(self, data):
        if self.done:
            return None
        self.buffer.extend(data)
        if self.headers is None:
            # The status/request line has already been consumed.
            marker = re.match(br'\r?\n', self.buffer)
            if marker is None:
                marker = re.search(br'\r?\n\r?\n', self.buffer)
            if marker is None:
                if len(self.buffer) > self.MAX_HEADERS:
                    self.finish()
                return None
            if marker.end() > self.MAX_HEADERS:
                self.finish()
                return None
            self.parser = BytesParser(policy=policy.default)
            self.headers = self.parser.parsebytes(bytes(self.buffer[:marker.end()]), headersonly=True)
            del self.buffer[:marker.end()]
            lengths = self.headers.get_all('Content-Length', [])
            content_type = self.headers.get_content_type()
            transfer = self.headers.get_all('Transfer-Encoding', [])
            self.chunked = len(transfer) == 1 and transfer[0].strip().lower() == 'chunked'
            if transfer and not self.chunked:
                return self.skip('transfer_encoding')
            if self.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                return self.skip('content_encoding')
            if not self.chunked and (len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,7}', lengths[0])):
                return self.skip('missing_or_invalid_content_length')
            generic_json = self.allow_generic_json and content_type in (
                'text/plain', 'text/html', 'application/octet-stream',
            )
            if content_type not in ('multipart/form-data', 'application/json') and not generic_json:
                return self.skip('unsupported_content_type', content_type)
            if not self.chunked:
                self.length = int(lengths[0])
                if not 0 < self.length <= self.MAX_BODY:
                    return self.skip('empty_or_oversized_body')
        if self.chunked:
            body = self.read_chunks()
            if body is None or isinstance(body, dict):
                return body
        else:
            if len(self.buffer) < self.length:
                return None
            body = bytes(self.buffer[:self.length])
        self.finish()
        if self.headers.get_content_type() != 'multipart/form-data':
            summary = self.json_summary(body)
            if summary is None:
                return self.skip('invalid_json')
            return dict(form_fields=[], **summary)
        message = self.parser.parsebytes(self.headers.as_bytes() + body)
        if not message.is_multipart() or message.defects:
            return None
        fields = []
        keys = []
        for part in message.iter_parts():
            name = part.get_param('name', header='Content-Disposition')
            if isinstance(name, str):
                fields.append(name)
            if name == 'data' and not part.is_multipart():
                keys.extend(self.json_keys(part.get_payload(decode=True) or b'') or [])
        return dict(form_fields=self.names(fields), json_keys=sorted(set(keys))[:128])

    def read_chunks(self):
        while True:
            if self.chunk_length is None:
                end = self.buffer.find(b'\r\n')
                if end < 0:
                    return self.skip('invalid_chunk_size') if len(self.buffer) > 1024 else None
                size = bytes(self.buffer[:end]).partition(b';')[0]
                if end > 1024 or not re.fullmatch(br'[0-9a-fA-F]{1,8}', size):
                    return self.skip('invalid_chunk_size')
                self.chunk_length = int(size, 16)
                del self.buffer[:end + 2]
                if self.chunk_length + len(self.decoded) > self.MAX_BODY:
                    return self.skip('empty_or_oversized_body')
            if self.chunk_length == 0:
                if self.buffer.startswith(b'\r\n') or b'\r\n\r\n' in self.buffer[:self.MAX_HEADERS]:
                    return bytes(self.decoded)
                return self.skip('oversized_trailers') if len(self.buffer) > self.MAX_HEADERS else None
            end = self.chunk_length
            if len(self.buffer) < end + 2:
                return None
            if self.buffer[end:end + 2] != b'\r\n':
                return self.skip('invalid_chunk_boundary')
            self.decoded.extend(self.buffer[:end])
            del self.buffer[:end + 2]
            self.chunk_length = None

    def skip(self, reason, content_type=None):
        self.finish()
        result = dict(form_fields=[], json_keys=[], body_skip_reason=reason)
        if content_type in ('text/html', 'text/plain', 'application/octet-stream'):
            result['body_content_type'] = content_type
        return result

    def finish(self):
        self.done = True
        self.buffer.clear()
        self.decoded.clear()
