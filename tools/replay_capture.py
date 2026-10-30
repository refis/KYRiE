"""Reframe explicitly recorded receive bytes without searching for boundaries."""
import argparse
from collections import Counter
import json
from pathlib import Path

from parser.definitions import load_lengths
from parser.framer import FramingError, PacketFramer
from capture.receiver import Receiver
from events import PacketEvent


class ReplayCancelled(Exception):
    """Cooperative cancellation; no partial result is published by GUI callers."""


def replay(path, definitions, on_packet=None, *, is_cancelled=None, on_progress=None,
           max_line_chars=None, max_input_chars=None):
    framers, failed, boundaries = {}, set(), {}
    counts = Counter()
    direction_counts = {'RECV': Counter(), 'SEND': Counter()}
    errors = []
    saw_payload_mode = False
    ended = False
    chunks = 0
    tcp_receiver = None
    callback_error = None

    class Collector:
        def write(self, kind, **fields):
            if kind == 'framing_error':
                errors.append(fields)

    allow_midstream = False

    def count_packet(event):
        nonlocal callback_error
        if callback_error is not None:
            return
        if is_cancelled and is_cancelled():
            callback_error = ReplayCancelled()
            return
        if on_packet is not None:
            try:
                on_packet(event)
            except Exception as exc:
                # Receiver isolates live consumer errors. Replay must propagate
                # them at the segment boundary rather than publish partial data.
                callback_error = exc
                return
        counts.update([event.packet_id])
        direction_counts[event.direction].update([event.packet_id])
    with Path(path).open(encoding='utf-8') as source:
        lines = iter(lambda: source.readline(max_line_chars + 1), '') if max_line_chars is not None else source
        input_chars = 0
        for lineno, line in enumerate(lines, 1):
            input_chars += len(line)
            if max_input_chars is not None and input_chars > max_input_chars:
                raise ValueError('Replay input exceeds configured size limit')
            if is_cancelled and is_cancelled():
                raise ReplayCancelled()
            if max_line_chars is not None and len(line) > max_line_chars:
                raise ValueError('Replay line exceeds configured size limit')
            if on_progress and (lineno == 1 or lineno % 256 == 0):
                on_progress(lineno)
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f'Invalid JSONL at line {lineno}; log may be incomplete') from exc
            if not isinstance(row, dict):
                raise ValueError(f'Invalid JSONL record at line {lineno}')
            kind = row.get('kind')
            if kind == 'session_start':
                if row.get('schema') != 1 or not row.get('record_payload'):
                    raise ValueError('Replay requires a schema 1 session with Record receive bytes for replay enabled')
                saw_payload_mode = True
            if kind == 'session_end':
                ended = True
            if kind == 'capture_options':
                allow_midstream = row.get('allow_midstream', False)
            if kind == 'capture_format' and row.get('transport') == 'tcp_segments':
                tcp_receiver = Receiver('', None, definitions,
                    count_packet, lambda message: None, process_pid=0,
                    allow_midstream=allow_midstream, recorder=Collector(),
                    capture_send=row.get('capture_send', False))
            if tcp_receiver is not None:
                if kind == 'tcp_segment':
                    if not saw_payload_mode or 'data_hex' not in row:
                        raise ValueError(f'TCP segment bytes missing at line {lineno}')
                    data = bytes.fromhex(row['data_hex'])
                    if len(data) != row['byte_count']:
                        raise ValueError(f'Byte count mismatch at line {lineno}')
                    chunks += 1
                    tcp_receiver._consume(tuple(row['endpoints']), row['sequence'], row['flags'],
                                          data, row['timestamp'], direction=row.get('direction', 'RECV'))
                    if callback_error is not None:
                        raise callback_error
                continue
            if kind not in ('connection_start', 'stream_chunk'):
                continue
            if not saw_payload_mode:
                raise ValueError('Session header is missing')
            key = (tuple(row['endpoints']), row['initial_sequence'])
            if kind == 'connection_start':
                boundaries[key] = row['boundary']
                continue
            if 'data_hex' not in row:
                raise ValueError(f'Stream bytes missing at line {lineno}')
            data = bytes.fromhex(row['data_hex'])
            if len(data) != row['byte_count']:
                raise ValueError(f'Byte count mismatch at line {lineno}')
            chunks += 1
            if key in failed:
                continue
            framer = framers.setdefault(key, PacketFramer(definitions))
            if row['stream_offset'] != framer.received_bytes:
                raise ValueError(f'Missing or reordered recorded stream chunks at line {lineno}')
            try:
                packets = framer.feed(data)
            except FramingError as exc:
                packets = exc.completed_packets
                failed.add(key)
                errors.append(dict(endpoints=list(key[0]), initial_sequence=key[1],
                    boundary=boundaries.get(key, 'UNKNOWN'), message=str(exc), **framer.snapshot()))
            boundary = boundaries.get(key, 'UNKNOWN')
            for pid, raw in packets:
                count_packet(PacketEvent(row.get('timestamp', 0.0), 'RECV', pid, raw, 'NPCAP',
                                         f'{key[0]} [{boundary}={key[1]}]'))
                if callback_error is not None:
                    raise callback_error
    if not saw_payload_mode:
        raise ValueError('No supported receive-byte session header found')
    if tcp_receiver is not None:
        incomplete = [dict(endpoints=list(key), tcp_next_sequence=stream.next_seq,
                           tcp_pending_segments=len(stream.pending), direction=tcp_receiver.stream_directions.get(key, 'RECV'),
                           protocol_probe_bytes=len(tcp_receiver.protocol_probes[key].buffer), **framer.snapshot())
                      for key, (stream, framer) in tcp_receiver.connections.items()
                      if framer.buffer or stream.pending or tcp_receiver.protocol_probes[key].buffer]
        connection_count = tcp_receiver.stats['syn_connections'] + tcp_receiver.stats['assumed_boundaries']
        failed_count = len(errors) + tcp_receiver.stats['tcp_errors']
        tcp_stats = tcp_receiver.diagnostics()
    else:
        incomplete = [dict(endpoints=list(key[0]), initial_sequence=key[1], **framer.snapshot())
                      for key, framer in framers.items() if key not in failed and framer.buffer]
        connection_count, failed_count, tcp_stats = len(framers), len(failed), None
    return dict(schema=1, source_log=str(path), session_end_present=ended,
        observed_chunks=chunks, connection_count=connection_count, failed_connections=failed_count,
        packet_counts={f'0x{pid:04X}': count for pid, count in sorted(counts.items())},
        packet_counts_by_direction={direction: {f'0x{pid:04X}': count for pid, count in sorted(entries.items())}
                                   for direction, entries in direction_counts.items()},
        errors=errors, tcp_statistics=tcp_stats, incomplete_streams=incomplete,
        note='No unknown-ID skipping or inferred resynchronization. Successful framing alone does not prove layout compatibility.')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('log', type=Path)
    cli.add_argument('--definitions', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    if args.output.resolve() in (args.log.resolve(), args.definitions.resolve()):
        cli.error('Output must differ from log and definitions')
    report = replay(args.log, load_lengths(args.definitions))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{report["connection_count"]} connections, {report["failed_connections"]} stopped; {args.output}')


if __name__ == '__main__':
    main()
