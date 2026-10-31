"""Thread-safe JSONL diagnostics, with explicit opt-in stream recording."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from threading import Lock
import time
import uuid
from storage.observation_export import save_observation_bytes, MAX_EXPORT_BYTES


class SessionLog:
    def __init__(self, root, definitions, record_payload=False, max_bytes=64 * 1024 * 1024, overlay=None):
        self.directory = Path(root) / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / 'capture.jsonl'
        definition_text = ''.join(f'{pid:04X} {size}\n' for pid, size in sorted(definitions.items()))
        (self.directory / 'PacketLength.used.txt').write_text(definition_text, encoding='utf-8')
        start = dict(schema=1, record_payload=record_payload,
                     definitions_sha256=hashlib.sha256(definition_text.encode('utf-8')).hexdigest())
        if overlay is not None:
            from parser.packet_overlay import overlay_evidence, write_overlay_snapshot
            write_overlay_snapshot(self.directory, overlay)
            evidence = overlay_evidence(overlay)
            if evidence and evidence.get('sha256'):
                start['overlay_sha256'] = evidence['sha256']
            if evidence and evidence.get('path'):
                start['overlay_path'] = evidence['path']
            if evidence and evidence.get('packet_count') is not None:
                start['overlay_packet_count'] = evidence['packet_count']
        self.file = self.path.open('w', encoding='utf-8', newline='\n')
        self.lock = Lock()
        self.record_payload = record_payload
        self.max_bytes = max_bytes
        self.written = 0
        self.error = ''
        self.closed = False
        self.write('session_start', **start)

    def write(self, kind, data=None, **fields):
        with self.lock:
            if self.closed or self.error:
                return
            record = dict(kind=kind, recorded_at=time.time(), **fields)
            if data is not None:
                record['byte_count'] = len(data)
                if self.record_payload:
                    record['data_hex'] = data.hex()
            try:
                line = json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n'
                encoded_size = len(line.encode('utf-8'))
                if self.written + encoded_size > self.max_bytes:
                    self.error = 'Session log reached its size limit; further records were not saved'
                    return
                self.file.write(line)
                self.file.flush()
                self.written += encoded_size
            except (OSError, ValueError, TypeError) as exc:
                # Logging failures must not terminate capture or recursively log.
                self.error = f'Session log write failed: {exc}'

    def close(self):
        self.write('session_end')
        with self.lock:
            if not self.closed:
                self.closed = True
                try:
                    self.file.close()
                except OSError as exc:
                    self.error = f'Session log close failed: {exc}'

    def export(self, target, source_paths=()):
        with self.lock:
            target = Path(target)
            if target.resolve() != self.path.resolve():
                with self.path.open('rb') as source:
                    data = source.read(MAX_EXPORT_BYTES + 1)
                save_observation_bytes(target, data,
                    [self.path, self.directory / 'PacketLength.used.txt', *source_paths])
