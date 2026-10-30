"""Classify only a stream's initial bytes; never search for a later boundary."""
import re


class InitialProtocolProbe:
    STARTS = (b'HTTP/', b'GET ', b'POST ', b'HEAD ', b'PUT ', b'DELETE ',
              b'OPTIONS ', b'PATCH ', b'CONNECT ', b'TRACE ', b'PRI ')
    HTTP2_PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
    REQUEST = re.compile(br'(?:GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH|CONNECT|TRACE) [^\x00-\x20\x7f]+ HTTP/1\.[01]\r?\n')
    RESPONSE = re.compile(br'HTTP/1\.[01] [0-9]{3}(?: [^\r\n]*)?\r?\n')

    def __init__(self, definitions, max_start_line=8192, expected_account=None):
        self.definitions = definitions
        self.buffer = bytearray()
        self.max_start_line = max_start_line
        self.protocol = None
        self.expected_account = expected_account
        self.account_echo_consumed = False
        self.account_echo_reported = False

    def _finish(self, protocol):
        self.protocol = protocol
        data = bytes(self.buffer) if protocol == 'GAME' else b''
        self.buffer.clear()
        return protocol, data

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
                return self._finish('HTTP')
            if not self.HTTP2_PREFACE.startswith(candidate):
                return self._finish('GAME')
        elif b'\n' in candidate:
            line = candidate[:candidate.index(b'\n') + 1]
            valid = len(line) <= self.max_start_line and (self.REQUEST.fullmatch(line) or self.RESPONSE.fullmatch(line))
            return self._finish('HTTP' if valid else 'GAME')
        if len(candidate) >= self.max_start_line:
            return self._finish('GAME')
        return 'PENDING', b''
