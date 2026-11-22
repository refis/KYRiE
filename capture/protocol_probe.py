"""Classify only a stream's initial bytes; never search for a later boundary."""
import re
from capture.http_body import HttpBody

RATHENA_POST_ROUTES = frozenset(
    route.encode('ascii') for route in (
        '/charconfig/load', '/charconfig/save', '/userconfig/load', '/userconfig/save',
        '/emblem/download', '/emblem/upload', '/MerchantStore/load', '/MerchantStore/save',
        '/party/add', '/party/del', '/party/get', '/party/info', '/party/list', '/party/search',
    )
)


class InitialProtocolProbe:
    STARTS = (b'HTTP/', b'GET ', b'POST ', b'HEAD ', b'PUT ', b'DELETE ',
              b'OPTIONS ', b'PATCH ', b'CONNECT ', b'TRACE ', b'PRI ')
    HTTP2_PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
    REQUEST = re.compile(br'(?:GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH|CONNECT|TRACE) [^\x00-\x20\x7f]+ HTTP/1\.[01]\r?\n')
    RESPONSE = re.compile(br'HTTP/1\.[01] [0-9]{3}(?: [^\r\n]*)?\r?\n')

    def __init__(self, definitions, max_start_line=8192, expected_account=None, *, observe_body=False):
        self.definitions = definitions
        self.buffer = bytearray()
        self.max_start_line = max_start_line
        self.protocol = None
        self.http_summary = None
        self.observe_body = observe_body
        self.allow_generic_json = False
        self.body = None
        self.rathena_route = None
        self.awaiting_final = False
        self.in_interim_headers = False
        self.interim_bytes = 0
        self.expected_account = expected_account
        self.account_echo_consumed = False
        self.account_echo_reported = False

    def _finish(self, protocol):
        self.protocol = protocol
        data = bytes(self.buffer) if protocol == 'GAME' else b''
        if not self.awaiting_final and self.body is None:
            self.buffer.clear()
        return protocol, data

    def follow_response(self, data=b''):
        """Read responses after informational headers at known stream boundaries."""
        if not self.awaiting_final:
            return
        self.buffer.extend(data)
        while self.awaiting_final:
            end = self.buffer.find(b'\n')
            limit = 65536 if self.in_interim_headers else self.max_start_line
            if self.interim_bytes + (len(self.buffer) if end < 0 else end + 1) > limit:
                break
            if end < 0:
                return
            line = bytes(self.buffer[:end + 1])
            del self.buffer[:end + 1]
            if self.in_interim_headers:
                self.interim_bytes += len(line)
                if line in (b'\r\n', b'\n'):
                    self.in_interim_headers = False
                    self.interim_bytes = 0
                continue
            if not self.RESPONSE.fullmatch(line):
                break
            self.http_summary = self._response_summary(line)
            self.awaiting_final = self.in_interim_headers = self._is_interim()
            if not self.awaiting_final:
                self._start_response_body()
            yield self.http_summary
        self.awaiting_final = False
        if self.body is None:
            self.buffer.clear()

    @property
    def observing_http(self):
        return self.awaiting_final or (self.body is not None and not self.body.done)

    def feed_body(self, data=b''):
        if self.body is None:
            return None
        if self.buffer:
            data = bytes(self.buffer) + data
            self.buffer.clear()
        return self.body.feed(data)

    def _start_response_body(self):
        status = int(self.http_summary[1])
        if self.observe_body and status >= 200 and status not in (204, 304):
            self.body = HttpBody(allow_generic_json=self.allow_generic_json)

    @staticmethod
    def _response_summary(line):
        version, status, *_ = line.rstrip(b'\r\n').split(b' ', 2)
        return version.decode('ascii'), status.decode('ascii')

    def _is_interim(self):
        status = int(self.http_summary[1])
        return 100 <= status < 200 and status != 101

    def feed(self, data):
        if self.protocol is not None:
            return self.protocol, data if self.protocol == 'GAME' else b''
        self.buffer.extend(data)
        candidate = bytes(self.buffer)
        if self.expected_account is not None:
            expected = self.expected_account.to_bytes(4, 'little')
            if expected.startswith(candidate) and len(candidate) < 4:
                return 'PENDING', b''
            self.expected_account = None
            if candidate.startswith(expected):
                del self.buffer[:4]
                self.account_echo_consumed = True
                candidate = bytes(self.buffer)
                if not candidate:
                    return 'PENDING', b''
        # An explicitly defined game ID wins over an ASCII-looking prefix.
        if len(candidate) >= 2 and int.from_bytes(candidate[:2], 'little') in self.definitions:
            return self._finish('GAME')
        if not any(candidate.startswith(start) or start.startswith(candidate) for start in self.STARTS):
            return self._finish('GAME')
        if candidate.startswith(b'PRI '):
            if candidate.startswith(self.HTTP2_PREFACE):
                self.http_summary = ('HTTP/2.0', 'preface')
                return self._finish('HTTP')
            if not self.HTTP2_PREFACE.startswith(candidate):
                return self._finish('GAME')
        elif b'\n' in candidate:
            line = candidate[:candidate.index(b'\n') + 1]
            if len(line) <= self.max_start_line:
                if self.REQUEST.fullmatch(line):
                    method, target, version = line.rstrip(b'\r\n').split(b' ')
                    self.http_summary = (version.decode('ascii'), method.decode('ascii'))
                    path = target.partition(b'?')[0]
                    if method == b'POST' and path in RATHENA_POST_ROUTES:
                        self.rathena_route = path.decode('ascii')
                        if self.observe_body:
                            self.body = HttpBody()
                            del self.buffer[:len(line)]
                    return self._finish('HTTP')
                if self.RESPONSE.fullmatch(line):
                    self.http_summary = self._response_summary(line)
                    self.awaiting_final = self.in_interim_headers = self._is_interim()
                    if not self.awaiting_final:
                        self._start_response_body()
                    if self.awaiting_final or self.body is not None:
                        del self.buffer[:len(line)]
                    return self._finish('HTTP')
            return self._finish('GAME')
        if len(candidate) >= self.max_start_line:
            return self._finish('GAME')
        return 'PENDING', b''
