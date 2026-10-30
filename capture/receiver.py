import time
from threading import Event, RLock
from collections import Counter, OrderedDict
from events import PacketEvent
from scapy.all import AsyncSniffer, IP, IPv6, TCP, Padding
from scapy.interfaces import get_working_ifaces
from capture.tcp_reassembly import TCPReassembler
from capture.process_monitor import discover
from capture.protocol_probe import InitialProtocolProbe
from parser.framer import PacketFramer, FramingError


class Receiver:
    def __init__(self, server_ip, server_port, definitions, on_packet, on_status, iface=None, process_pid=None, include_children=False, allow_midstream=False, recorder=None, capture_send=False):
        self.server_ip = server_ip if process_pid is None else ''
        self.server_port = int(server_port) if process_pid is None and server_port not in (None, "") else None
        self.lock = RLock()
        self.initial_sequences = {}
        self.flow_states = OrderedDict()
        self.flow_serial = 0
        self.gap_since = {}
        self.gap_timeout = 30.0
        self.definitions = definitions
        self.on_packet = on_packet
        self.on_status = on_status
        self.iface = iface or None
        self.process_pid = process_pid
        self.include_children = include_children
        self.allow_midstream = allow_midstream
        self.capture_send = capture_send
        if capture_send and process_pid is None and not self.server_ip and self.server_port is None:
            raise ValueError('Manual SEND capture requires a remote Server IP or Port; select an EXE for automatic direction detection')
        self.stream_directions = {}
        self.protocol_probes = {}
        self.passed_http = set()
        self.midstream_keys = set()
        self.allowed = set()
        self.active_endpoints = set()
        self.syn_seen = {}
        self.on_connections = lambda endpoints: None
        self.connections = {}
        self.sniffer = None
        self.stats = Counter()
        self.waiting_notified = set()
        self.early_segments = {}
        self.early_bytes = 0
        self.early_count = 0
        self.max_early_bytes = 2 * 1024 * 1024
        self.max_early_count = 4096
        self.capture_interfaces = []
        self.ready = False
        self.stop_requested = Event()
        self.recorder = recorder
        self._record('capture_format', transport='tcp_segments', capture_send=capture_send)

    @staticmethod
    def reverse_key(key):
        return (key[2], key[3], key[0], key[1])

    def _owned_direction(self, key):
        if key in self.allowed:
            return 'RECV'
        if self.capture_send and self.reverse_key(key) in self.allowed:
            return 'SEND'
        return None

    def _manual_direction(self, key):
        incoming = ((not self.server_ip or key[0] == self.server_ip)
                    and (self.server_port is None or key[1] == self.server_port))
        outgoing = (self.capture_send and (not self.server_ip or key[2] == self.server_ip)
                    and (self.server_port is None or key[3] == self.server_port))
        if incoming and outgoing:
            return None  # Ambiguous endpoints must not be assigned a guessed direction.
        return 'RECV' if incoming else 'SEND' if outgoing else None

    def _record(self, kind, **fields):
        if self.recorder is not None:
            self.recorder.write(kind, **fields)

    def _emit_packet(self, key, timestamp, pid, raw):
        boundary = 'ASSUMED' if key in self.midstream_keys else 'SYN'
        connection = f'{key} [{boundary}={self.initial_sequences[key]}]'
        direction = self.stream_directions.get(key, 'RECV')
        canonical = key if direction == 'RECV' else self.reverse_key(key)
        flow_id = self.flow_states.get(canonical, {}).get('id', '')
        if (direction == 'SEND' and pid == 0x65 and len(raw) == 17 and raw[16] in (0, 1)
                and key not in self.midstream_keys and canonical not in self.midstream_keys):
            account = int.from_bytes(raw[2:6], 'little')
            if account:
                self.flow_states[canonical]['expected_account'] = account
                peer_probe = self.protocol_probes.get(canonical)
                if peer_probe is not None and peer_probe.protocol is None and not peer_probe.account_echo_consumed:
                    peer_probe.expected_account = account
        self.on_packet(PacketEvent(timestamp, direction, pid, raw, 'NPCAP', connection, flow_id))
        self.stats['framed_packets'] += 1
        self.stats[direction.lower() + '_packets'] += 1
        self._record('packet', connection=connection, timestamp=timestamp, packet_id=pid,
                     length=len(raw), definition_length=self.definitions[pid], direction=direction)

    def diagnostics(self):
        with self.lock:
            return dict(self.stats, tracked=len(self.allowed), streams=len(self.connections),
                        early_bytes=self.early_bytes, ready=self.ready)

    def check_health(self):
        if self.sniffer is None:
            return
        error = getattr(self.sniffer, 'exception', None)
        if error is not None:
            raise RuntimeError(f'Npcap capture failed: {error}') from error
        thread = getattr(self.sniffer, 'thread', None)
        if thread is not None and not thread.is_alive():
            raise RuntimeError('Npcap capture thread stopped unexpectedly')

    def _handle(self, pkt):
        with self.lock:
            self._handle_locked(pkt)

    def _handle_locked(self, pkt):
        try:
            if TCP not in pkt:
                return
            self.stats['observed_tcp'] += 1
            ip = pkt[IP] if IP in pkt else pkt[IPv6] if IPv6 in pkt else None
            if ip is None:
                return
            tcp = pkt[TCP]
            key = (ip.src, int(tcp.sport), ip.dst, int(tcp.dport))
            # Scapy attaches link-layer padding below TCP/Raw. These bytes are
            # outside IP's declared length and consume no TCP sequence numbers.
            # In particular an ACK / Padding is not application payload.
            payload = bytes(tcp.payload)
            padding = tcp.getlayer(Padding)
            if padding is not None:
                padding_size = len(bytes(padding))
                if padding_size:
                    payload = payload[:-padding_size]
                    self.stats['ignored_padding_bytes'] += padding_size
            seq, flags, timestamp = int(tcp.seq), int(tcp.flags), float(pkt.time)
            direction = self._owned_direction(key) if self.process_pid is not None else self._manual_direction(key)
            if self.process_pid is not None and direction is None:
                self.stats['not_owned'] += 1
                self._cache_early(key, seq, flags, payload, timestamp)
                return
            if direction is not None:
                self._consume(key, seq, flags, payload, timestamp, direction=direction)
        except Exception as e:
            self.on_status(f'Capture error: {e}')

    def _consume(self, key, seq, flags, payload, timestamp, direction='RECV'):
        if direction not in ('RECV', 'SEND'):
            raise ValueError('Unsupported TCP stream direction')
        self.stream_directions[key] = direction
        self.stats['matched_segments'] += 1
        self.stats['matched_payload_bytes'] += len(payload)
        syn = bool(flags & 0x02)
        canonical = key if direction == 'RECV' else self.reverse_key(key)
        state = self.flow_states.get(canonical)
        if state is None or (syn and direction in state and state[direction] != seq):
            self.flow_serial += 1
            state = {'id': f'tcp-{self.flow_serial}'}
            self.flow_states[canonical] = state
        if syn:
            state[direction] = seq
        self.flow_states.move_to_end(canonical)
        if len(self.flow_states) > 4096:
            self.flow_states.popitem(last=False)
        if syn and self.initial_sequences.get(key) != seq:
            # Early process-discovery replay may deliver an already classified
            # request before the opposite half's cached SYN/ACK is replayed.
            deferred_peer_syn = (key in self.passed_http and key not in self.initial_sequences
                                 and bool(flags & 0x10) and self.reverse_key(key) in self.initial_sequences)
            if deferred_peer_syn:
                self.initial_sequences[key] = seq
            else:
                self.passed_http.discard(key)
                self.passed_http.discard(self.reverse_key(key))
        if key in self.passed_http:
            self.stats['passed_http_segments'] += 1
            self._record('protocol_pass_segment', endpoints=key, sequence=seq, flags=flags,
                         timestamp=timestamp, byte_count=len(payload), direction=direction, protocol='HTTP')
            return
        # Retain the original segment sequence even after framing stops, so a
        # corrected definition can be replayed against later received data.
        self._record('tcp_segment', endpoints=key, sequence=seq, flags=flags,
                     timestamp=timestamp, data=payload, direction=direction)
        try:
            if syn and self.initial_sequences.get(key) != seq:
                self.connections[key] = (TCPReassembler(), PacketFramer(self.definitions))
                self.protocol_probes[key] = InitialProtocolProbe(self.definitions,
                    expected_account=state.get('expected_account') if direction == 'RECV' else None)
                self.initial_sequences[key] = seq
                self.midstream_keys.discard(key)
                self.gap_since.pop(key, None)
                self.waiting_notified.discard(key)
                self.stats['syn_connections'] += 1
                self._record('connection_start', endpoints=key, initial_sequence=seq, boundary='SYN', direction=direction)
            if (key not in self.connections and key not in self.initial_sequences
                    and payload and not flags & 0x05 and self.allow_midstream):
                stream = TCPReassembler()
                stream.start_at(seq)
                self.connections[key] = (stream, PacketFramer(self.definitions))
                self.protocol_probes[key] = InitialProtocolProbe(self.definitions)
                self.initial_sequences[key] = seq
                self.midstream_keys.add(key)
                self.stats['assumed_boundaries'] += 1
                self._record('connection_start', endpoints=key, initial_sequence=seq, boundary='ASSUMED', direction=direction)
                self.on_status(f'Attaching existing TCP connection at first payload; '
                               f'packet boundary is assumed, not verified: {key}')
            if key not in self.connections:
                # Do not parse midstream payload as a packet boundary.
                if payload and key in self.initial_sequences:
                    self.stats['stopped_stream_segments'] += 1
                    return
                if payload:
                    self.stats['waiting_syn_segments'] += 1
                    if key not in self.waiting_notified:
                        if len(self.waiting_notified) >= 4096:
                            self.waiting_notified.clear()
                        self.waiting_notified.add(key)
                        self.on_status(f'{direction} TCP payload received but stream boundary unavailable; '
                                       f'keep capture running and reconnect the game: {key}')
                return
            if flags & 0x04:
                self.connections.pop(key, None)
                if self.capture_send:
                    self.connections.pop(self.reverse_key(key), None)
                return
            stream, framer = self.connections[key]
            for chunk in stream.feed(seq, payload, syn=syn):
                probe = self.protocol_probes[key]
                protocol, chunk = probe.feed(chunk)
                if probe.account_echo_consumed and not probe.account_echo_reported:
                    probe.account_echo_reported = True
                    self.stats['verified_account_echoes'] += 1
                    self._record('account_echo', endpoints=key, direction=direction, timestamp=timestamp,
                                 flow_id=state['id'], byte_count=4, basis='matching_character_login')
                if protocol == 'HTTP':
                    self._pass_http(key, timestamp, direction)
                    return
                if protocol == 'PENDING':
                    continue
                self._record('stream_chunk', endpoints=key, initial_sequence=self.initial_sequences[key],
                             timestamp=timestamp, stream_offset=framer.received_bytes,
                             tcp_segment_sequence=seq, data=chunk, direction=direction)
                for pid, raw in framer.feed(chunk):
                    self._emit_packet(key, timestamp, pid, raw)
            if stream.failed:
                self.stats['tcp_errors'] += 1
                self.on_status(f'TCP stream stopped (buffer limit or conflicting overlap): {key}')
                self.connections.pop(key, None)
            elif stream.pending:
                self.gap_since.setdefault(key, time.monotonic())
            else:
                self.gap_since.pop(key, None)
            if flags & 0x01:
                self.connections.pop(key, None)
        except FramingError as e:
            for pid, raw in e.completed_packets:
                self._emit_packet(key, timestamp, pid, raw)
            self.stats['framing_errors'] += 1
            context = framer.snapshot()
            self._record('framing_error', endpoints=key, initial_sequence=self.initial_sequences[key],
                         timestamp=timestamp, message=str(e), boundary=('ASSUMED' if key in self.midstream_keys else 'SYN'),
                         tcp_next_sequence=stream.next_seq, tcp_pending_segments=len(stream.pending), direction=direction, **context)
            previous = context['previous_packets'][-1] if context['previous_packets'] else None
            detail = (f'; previous=0x{previous["packet_id"]:04X} '
                      f'length={previous["applied_length"]}' if previous else '; previous=none')
            self.on_status(f'{direction} framing stopped for {key}: {e}; offset={framer.offset}{detail}')
            self.connections.pop(key, None)
        except Exception as e:
            self.on_status(f'Capture error: {e}')

    def _pass_http(self, key, timestamp, direction):
        for half in (key, self.reverse_key(key)):
            self.passed_http.add(half)
            self.connections.pop(half, None)
            self.protocol_probes.pop(half, None)
            self.gap_since.pop(half, None)
        self.stats['passed_http_connections'] += 1
        self._record('protocol_pass', endpoints=key, timestamp=timestamp, direction=direction,
                     protocol='HTTP', reason='recognized initial HTTP start line or HTTP/2 preface')
        self.on_status(f'PASS HTTP connection (both directions): {key}')

    def _discard_early(self, key):
        segments = self.early_segments.pop(key, [])
        self.early_bytes -= sum(len(segment[2]) for segment in segments)
        self.early_count -= len(segments)
        self.syn_seen.pop(key, None)
        return segments

    def _cache_early(self, key, seq, flags, payload, timestamp):
        now = time.monotonic()
        for old_key, (_, seen_at) in list(self.syn_seen.items()):
            if now - seen_at > 30:
                self._discard_early(old_key)
        if flags & 0x02:
            if key not in self.syn_seen or self.syn_seen[key][0] != seq:
                self._discard_early(key)
                self.syn_seen[key] = (seq, now)
        if key not in self.syn_seen or not (payload or flags & 0x07):
            return
        if self.early_bytes + len(payload) > self.max_early_bytes or self.early_count >= self.max_early_count:
            # Dropping any prefix invalidates the boundary: discard the SYN too.
            self._discard_early(key)
            self.stats['early_overflows'] += 1
            return
        self.early_segments.setdefault(key, []).append((seq, flags, payload, timestamp))
        self.early_bytes += len(payload)
        self.early_count += 1

    def refresh_connections(self):
        if self.process_pid is None:
            with self.lock:
                self._expire_gaps()
            return
        try:
            endpoints = discover(self.process_pid, self.include_children)
        except Exception:
            # Ownership cannot be confirmed; do not continue on stale socket data.
            with self.lock:
                self.allowed.clear()
                self.connections.clear()
                self.initial_sequences.clear()
                self.midstream_keys.clear()
                self.stream_directions.clear()
                self.protocol_probes.clear()
                self.passed_http.clear()
                self.syn_seen.clear()
                self.early_segments.clear()
                self.early_bytes = self.early_count = 0
                self.gap_since.clear()
                self.active_endpoints = set()
            self.on_connections([])
            raise
        with self.lock:
            self._update_connections(endpoints)
        self.on_connections(sorted(endpoints, key=lambda e: (e.remote_ip, e.remote_port)))

    def _update_connections(self, endpoints):
        self._expire_gaps()
        self.allowed = {e.key for e in endpoints}
        for key in (set(self.connections) | set(self.initial_sequences) | set(self.stream_directions)
                    | set(self.protocol_probes) | self.passed_http):
            if self._owned_direction(key) is None:
                self.connections.pop(key, None)
                self.initial_sequences.pop(key, None)
                self.midstream_keys.discard(key)
                self.stream_directions.pop(key, None)
                self.protocol_probes.pop(key, None)
                self.passed_http.discard(key)
                self.gap_since.pop(key, None)
        for key, (seq, seen_at) in list(self.syn_seen.items()):
            if time.monotonic() - seen_at > 30:
                self._discard_early(key)
                continue
            direction = self._owned_direction(key)
            if direction is not None:
                for segment in self._discard_early(key):
                    self._consume(key, *segment, direction=direction)
        self.active_endpoints = endpoints

    def _expire_gaps(self):
        for key, since in list(self.gap_since.items()):
            if key not in self.connections:
                self.gap_since.pop(key, None)
            elif time.monotonic() - since >= self.gap_timeout:
                self.connections.pop(key, None)
                self.gap_since.pop(key, None)
                self.on_status(f'TCP gap timeout; reconnect required: {key}')

    def start(self):
        if self.sniffer is not None:
            return
        if self.process_pid is not None:
            self.refresh_connections()
        filters = ['tcp']
        if self.server_ip:
            filters.append(f'{"host" if self.capture_send else "src host"} {self.server_ip}')
        if self.server_port is not None:
            filters.append(f'{"port" if self.capture_send else "src port"} {self.server_port}')
        bpf = ' and '.join(filters)
        self.capture_interfaces = [self.iface] if self.iface else get_working_ifaces()
        if not self.capture_interfaces:
            raise RuntimeError('No usable Npcap interfaces found; check Npcap installation and permissions')
        self.ready = False
        self.stop_requested.clear()

        def started():
            if self.stop_requested.is_set() or self.sniffer is not sniffer:
                sniffer.stop(join=False)
            else:
                self._started()

        sniffer = AsyncSniffer(filter=bpf, iface=self.capture_interfaces,
                               prn=self._handle, store=False, started_callback=started)
        self.sniffer = sniffer
        names = ', '.join(str(getattr(iface, 'name', iface)) for iface in self.capture_interfaces)
        self.on_status(f'Opening Npcap interfaces: {names}; filter: {bpf}')
        self.sniffer.start()

    def _started(self):
        self.ready = True
        self.on_status('Npcap capture ready; ' + ('existing-connection attachment enabled'
                       if self.allow_midstream else 'now log in or reconnect the game to observe TCP SYN'))

    def stop(self):
        self.stop_requested.set()
        if self.sniffer is not None:
            sniffer, self.sniffer = self.sniffer, None
            # A not-yet-open sniffer is stopped by its started callback. A failed
            # thread may leave running=True without ever installing stop_cb.
            if sniffer.running and hasattr(sniffer, 'stop_cb'):
                try:
                    sniffer.stop()
                except Exception as exc:
                    self.on_status(f'Capture shutdown error: {exc}')
        self.connections.clear()
        self.allowed.clear()
        self.syn_seen.clear()
        self.early_segments.clear()
        self.early_bytes = self.early_count = 0
        self.waiting_notified.clear()
        self.ready = False
        self.initial_sequences.clear()
        self.midstream_keys.clear()
        self.stream_directions.clear()
        self.protocol_probes.clear()
        self.passed_http.clear()
        self.gap_since.clear()
        self.on_status('Stopped')
