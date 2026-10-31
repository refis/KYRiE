"""MOB skill evidence; intervals are computed per appearance before aggregation."""
from collections import Counter, deque
import json
import hashlib
import math
from pathlib import Path
from statistics import median

from reconstruction.decoder import Reader, ObservationError

DEFAULT_NAMES = Path(__file__).resolve().parent.parent / 'config' / 'skill_names.json'


def load_skill_names(path=DEFAULT_NAMES):
    return load_skill_names_with_hash(path)[0]


def load_skill_names_with_hash(path=DEFAULT_NAMES):
    with Path(path).open('rb') as stream:
        raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024:
        raise ValueError('Skill dictionary exceeds 1 MiB')
    return validate_skill_names(json.loads(raw.decode('utf-8'))),hashlib.sha256(raw).hexdigest()


def validate_skill_names(document):
    """Validate the name map. version/source/name_resolution stay provenance, not names."""
    if (not isinstance(document, dict) or type(document.get('version')) is not int
            or document.get('version') != 1 or not isinstance(document.get('skills'), dict)):
        raise ValueError('Invalid skill dictionary')
    source = document.get('source', None)
    if source is not None and (not isinstance(source, str) or not 1 <= len(source) <= 1024):
        raise ValueError('Invalid skill dictionary source')
    resolution = document.get('name_resolution', None)
    if resolution is not None:
        if not isinstance(resolution, dict) or len(json.dumps(resolution, ensure_ascii=True)) > 65536:
            raise ValueError('Invalid skill dictionary name_resolution')
        for key in ('policy', 'encoding'):
            value = resolution.get(key, None)
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 256):
                raise ValueError('Invalid skill dictionary name_resolution')
        catalog_version = resolution.get('catalog_version', None)
        if catalog_version is not None and type(catalog_version) is not int:
            raise ValueError('Invalid skill dictionary name_resolution')
        sources = resolution.get('sources', None)
        if sources is not None and not isinstance(sources, list):
            raise ValueError('Invalid skill dictionary name_resolution')
    result = {}
    for key, value in document['skills'].items():
        if (not key.isascii() or not key.isdecimal() or str(int(key)) != key or not 0 < int(key) <= 65535
                or not isinstance(value, str) or not 0 < len(value) <= 256):
            raise ValueError('Invalid skill dictionary entry')
        result[int(key)] = value
    return result


def decode_skill(packet):
    if packet.direction != 'RECV':
        return None
    r, pid = Reader(packet.raw), packet.packet_id
    if pid in (0x13e, 0x7fb):
        r.take(0, 24 if pid == 0x13e else 25)
        return 'cast', r.number(2, 'I'), dict(target_id=r.number(6, 'I'), x=r.number(10, 'H'),
            y=r.number(12, 'H'), skill_id=r.number(14, 'H'), cast_ms=r.number(20, 'I'))
    if pid == 0x1b9:
        return 'cancel', r.number(2, 'I'), {}
    if pid == 0x1de:
        r.take(0, 33)
        return 'damage', r.number(4, 'I'), dict(skill_id=r.number(2, 'H'), target_id=r.number(8, 'I'),
            server_tick=r.number(12, 'I'), source_delay=r.number(16, 'i'), target_delay=r.number(20, 'i'),
            damage=r.number(24, 'i'), level_raw=r.number(28, 'H'), divisions=r.number(30, 'h'), hit=r.number(32, 'B'))
    if pid in (0x11a, 0x9cb):
        modern = pid == 0x9cb
        r.take(0, 17 if modern else 15)
        return 'effect', r.number(12 if modern else 10, 'I'), dict(skill_id=r.number(2, 'H'),
            effect_value=r.number(4, 'i' if modern else 'h'), target_id=r.number(8 if modern else 6, 'I'),
            result=r.number(16 if modern else 14, 'B'))
    if pid == 0x117:
        r.take(0, 18)
        return 'ground', r.number(4, 'I'), dict(skill_id=r.number(2, 'H'), level_raw=r.number(8, 'H'),
            x=r.number(10, 'H'), y=r.number(12, 'H'), server_tick=r.number(14, 'I'))
    return None


def _ms(start, end):
    if not (math.isfinite(start) and math.isfinite(end)) or end < start:
        return None
    value = (end - start) * 1000
    return round(value, 3) if math.isfinite(value) else None


class SkillStore:
    def __init__(self, world, max_events=100000, max_entries=10000):
        self.world = world
        self.max_events, self.max_entries = max_events, max_entries
        self.events = []
        self.buckets = {}
        self.pending = {}
        self.anchors = {}
        self.revision = 0
        self.issue_count = 0
        self.issues = deque(maxlen=100)
        self.unattributed = 0
        self.unmatched_cancels = deque(maxlen=100)
        self.current_capture = -1
        self.packet_ordinal = 0
        self.saturated = False

    def begin_capture(self, session):
        if session > self.current_capture:
            self.current_capture = session
            for record in self.pending.values():
                record['cast_outcome'] = 'capture_changed'
                record['tracking_end'] = dict(reason='capture_changed', next_capture_session=session)
            self.pending.clear()
            self.anchors.clear()
            self.revision += 1

    def _entity(self, packet, session, actor):
        return self.world.find_current(packet, session, actor, kind='MOB')

    def _issue(self, packet, index, message):
        self.issue_count += 1
        self.issues.append(dict(packet_index=index, packet_id=packet.packet_id, message=message))
        self.revision += 1

    def apply(self, packet, session=0, packet_index=None):
        self.begin_capture(session)
        index = self.packet_ordinal if packet_index is None else packet_index
        self.packet_ordinal += 1
        if session != self.current_capture:
            return
        # Remove pending casts at lifecycle boundaries; never carry them to a new appearance.
        if packet.direction == 'RECV' and packet.packet_id in (0x80, 0x91, 0x92, 0x1b0, 0x9fe, 0x9ff, 0x9fd):
            for key in list(self.pending):
                entity = self.world.entities.get(key[0])
                if entity is None or not entity.active or entity.class_id != key[1]:
                    record = self.pending.pop(key)
                    record['cast_outcome'] = 'interrupted'
                    reason = ('entity_missing' if entity is None else
                              'class_changed' if entity.class_id != key[1] else entity.state)
                    record['tracking_end'] = dict(reason=reason, packet_index=index, packet_id=packet.packet_id,
                        timestamp=packet.timestamp, capture_session=session, connection=packet.connection)
                    self.revision += 1
        if self.saturated:
            return
        try:
            decoded = decode_skill(packet)
        except ObservationError as exc:
            self._issue(packet, index, str(exc))
            self._end_pending('decode_error', packet, index, session)
            self.pending.clear()
            self.anchors.clear()
            return
        if decoded is None:
            return
        kind, actor, fields = decoded
        entity = self._entity(packet, session, actor)
        if entity is None:
            self.unattributed += 1
            self.revision += 1
            return
        identity = (entity.key, entity.class_id)
        reference = dict(packet_index=index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                         capture_session=session, connection=packet.connection, source=packet.source)
        if kind == 'cancel':
            pending = self.pending.get(identity)
            if pending is None:
                self.unmatched_cancels.append(dict(reference, actor_id=actor, entity_key=entity.key))
                self.revision += 1
                return
            fields['skill_id'] = pending['skill_id']
            fields['linked_cast_index'] = pending['packet_index']
        bucket_key = (*identity, fields['skill_id'])
        if len(self.events) >= self.max_events or (bucket_key not in self.buckets and len(self.buckets) >= self.max_entries):
            self.saturated = True
            self._end_pending('capacity_reached', packet, index, session)
            self.pending.clear()
            self.anchors.clear()
            self._issue(packet, index, 'Skill observation capacity reached; further observations disabled')
            return
        if kind == 'cancel':
            self.pending.pop(identity)['cast_outcome'] = 'cancelled'
        flags = []
        if not math.isfinite(packet.timestamp) or packet.timestamp < entity.first_seen:
            flags.append('invalid_time')
        if ' [ASSUMED=' in packet.connection:
            flags.append('assumed_boundary')
        target = fields.get('target_id')
        target_kind = ('ground' if kind == 'ground' else 'unknown' if target in (None, 0)
                       else 'self' if target == actor else 'observed_mob' if self._entity(packet, session, target)
                       else 'other')
        record = dict(reference, kind=kind, actor_id=actor, entity_key=entity.key, class_id=entity.class_id,
                      name=entity.name, map_name=entity.map_name, target_kind=target_kind,
                      movement='moving' if entity.destination_x is not None else 'stationary_observed',
                      flags=flags, interval_ms=None, interval_basis=None, interval_from_packet_index=None,
                      tick_group_new=False, **fields)
        raw_level = fields.get('level_raw')
        record['level'] = raw_level if raw_level is not None and 0 < raw_level < 0x8000 else None
        previous_cast = self.pending.get(identity)
        if kind == 'cast':
            if previous_cast:
                previous_cast['cast_outcome'] = 'superseded'
                previous_cast['tracking_end'] = dict(reason='superseded', packet_index=index,
                    packet_id=packet.packet_id, timestamp=packet.timestamp,
                    capture_session=session, connection=packet.connection)
            record['cast_outcome'] = 'pending'
            self.pending[identity] = record
        elif kind in ('damage', 'effect', 'ground') and previous_cast and previous_cast['skill_id'] == fields['skill_id']:
            elapsed = _ms(previous_cast['timestamp'], packet.timestamp)
            previous_target = previous_cast.get('target_id')
            target_matches = not previous_target or not target or previous_target == target
            if kind == 'ground':
                target_matches = (fields['x'], fields['y']) == (previous_cast['x'], previous_cast['y'])
            if (not flags and 'invalid_time' not in previous_cast['flags'] and elapsed is not None
                    and elapsed <= previous_cast['cast_ms'] + 1500 and target_matches):
                record['linked_cast_index'] = previous_cast['packet_index']
                record['cast_elapsed_ms'] = elapsed
                record['cast_link_status'] = 'candidate'
                previous_cast['cast_outcome'] = 'effect_observed'
                self.pending.pop(identity)
        # Arrival-based notifications and tick-based damage/ground intervals are
        # separate series. Effect notifications are not counted as skill uses.
        if kind in ('cast', 'damage', 'ground', 'effect') and (kind != 'effect' or fields['target_id'] != 0):
            anchor_key = ((bucket_key, kind, fields['target_id'], fields['result'])
                          if kind == 'effect' else (bucket_key, kind))
            previous = self.anchors.get(anchor_key)
            basis = ('capture_cast_start' if kind == 'cast' else
                     'capture_effect_notification' if kind == 'effect' else f'server_tick_{kind}')
            record['interval_basis'] = basis
            tick = fields.get('server_tick')
            record['tick_group_new'] = tick is not None and (previous is None or previous.get('server_tick') != tick)
            if previous:
                elapsed = _ms(previous['timestamp'], packet.timestamp)
                if elapsed is None:
                    flags.append('timestamp_reversed')
                elif kind in ('cast', 'effect'):
                    record['interval_ms'] = elapsed if elapsed > 0 else None
                else:
                    delta = (tick - previous['server_tick']) & 0xffffffff
                    if 0 < delta < 0x80000000:
                        record['interval_ms'] = delta
                    elif delta >= 0x80000000:
                        flags.append('tick_reversed_or_ambiguous')
                if set(previous['flags']) & {'invalid_time', 'timestamp_reversed', 'tick_reversed_or_ambiguous', 'assumed_boundary'}:
                    flags.append('previous_observation_unreliable')
            if flags:
                record['interval_ms'] = None
            if previous and record['interval_ms'] is not None:
                record['interval_from_packet_index'] = previous['packet_index']
            self.anchors[anchor_key] = record
        self.events.append(record)
        self.buckets.setdefault(bucket_key, []).append(record)
        self.revision += 1

    def _end_pending(self, reason, packet, index, session):
        for record in self.pending.values():
            record['cast_outcome'] = reason
            record['tracking_end'] = dict(reason=reason, packet_index=index, packet_id=packet.packet_id,
                timestamp=packet.timestamp, capture_session=session, connection=packet.connection)

    def summaries(self, entity_key=None, aggregate=False):
        groups = {}
        for (identity, class_id, skill_id), records in self.buckets.items():
            if entity_key is not None and identity != entity_key:
                continue
            key = (class_id, skill_id) if aggregate else (identity, class_id, skill_id)
            groups.setdefault(key, []).extend(records)
        result = []
        for records in groups.values():
            counts = Counter(record['kind'] for record in records)
            intervals = {}
            for basis in ('capture_cast_start', 'server_tick_damage', 'server_tick_ground', 'capture_effect_notification'):
                samples = [dict(duration_ms=record['interval_ms'], packet_index=record['packet_index'],
                                from_packet_index=record['interval_from_packet_index'], entity_key=record['entity_key'],
                                **(dict(target_id=record['target_id'], result=record['result'])
                                   if basis == 'capture_effect_notification' else {})) for record in records
                           if record['interval_basis'] == basis and record['interval_ms'] is not None]
                values = [sample['duration_ms'] for sample in samples]
                intervals[basis] = dict(count=len(values), min_ms=min(values) if values else None,
                    median_ms=median(values) if values else None, max_ms=max(values) if values else None, samples=samples)
            first = records[0]
            result.append(dict(class_id=first['class_id'], skill_id=first['skill_id'],
                entity_key=None if aggregate else first['entity_key'], counts=dict(counts),
                source_appearances=len({record['entity_key'] for record in records}),
                known_levels=sorted({record['level'] for record in records if record['level'] is not None}),
                raw_levels=sorted({record['level_raw'] for record in records if 'level_raw' in record}),
                unknown_level_notifications=sum('level_raw' in record and record['level'] is None for record in records),
                tick_groups=sum(record['tick_group_new'] for record in records), intervals=intervals,
                cast_ms=sorted({record['cast_ms'] for record in records if 'cast_ms' in record}),
                targets=dict(Counter(record['target_kind'] for record in records)),
                issue_notifications=sum(bool(record['flags']) for record in records),
                evidence=[record['packet_index'] for record in records], configured_cooldown_ms=None))
        return sorted(result, key=lambda row: (row['class_id'] if row['class_id'] is not None else -1,
                                               row['skill_id'], str(row['entity_key'])))

    def snapshot(self):
        return dict(schema_version=1, individual_skills=self.summaries(), class_skills=self.summaries(aggregate=True),
                    observations=self.events, issue_count=self.issue_count, issues=list(self.issues),
                    unattributed_notifications=self.unattributed, unmatched_cancels=list(self.unmatched_cancels),
                    saturated=self.saturated, transport_quality='not_verified')
