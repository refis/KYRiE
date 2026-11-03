"""MOB visibility lifetimes, not server spawn counts or respawn configuration."""
from copy import deepcopy
import math

from reconstruction.decoder import decode_world_event, ObservationError
from reconstruction.actor_identity import actor_sort_key


class MobSpawnStore:
    def __init__(self, world, max_records=20000):
        self.world, self.max_records = world, max_records
        self.records, self.active, self.previous, self.groups = [], {}, {}, {}
        self.current_capture, self.revision, self.saturated = -1, 0, False
        self.world_issue_count = 0

    def _end(self, key, kind, timestamp=None, packet_index=None, reason=None):
        row = self.active.pop(key)
        if timestamp is not None and (not math.isfinite(timestamp) or timestamp < row['last_seen']):
            row['quality_flags'].append('invalid_end_time')
        row['end'] = dict(kind=kind, timestamp=timestamp, packet_index=packet_index, reason=reason)
        self.groups[row['group_key']]['tracked_now'] -= 1

    def apply(self, packet, session=0, packet_index=None):
        if session > self.current_capture:
            for key in list(self.active):
                self._end(key, 'capture_changed')
            self.previous.clear()
            self.current_capture = session
            self.revision += 1
        if session != self.current_capture or self.saturated:
            return
        if packet.direction != 'RECV' or packet.packet_id not in (0x9fe, 0x9ff, 0x9fd, 0x80, 0x91, 0x92):
            return
        try:
            event = decode_world_event(packet)
        except ObservationError:
            return  # WorldStore already retains decoder issues.
        scope = (session, packet.connection)
        if event.kind == 'map_changed':
            for key in list(self.active):
                if key[:2] == scope:
                    self._end(key, 'map_changed', packet.timestamp, packet_index)
            self.revision += 1
            return
        entity = self.world.find_current(packet, session, event.actor_id, 'MOB', active_only=False)
        if entity is None:
            scene = self.world.scenes.get(scope)
            key = (*scope, scene.generation, event.actor_id) if scene else None
            if event.kind == 'actor_seen' and key in self.active:
                self._end(key, 'appearance_or_class_changed', packet.timestamp, packet_index)
                self.revision += 1
            return
        actor_key = (*scope, entity.map_generation, entity.actor_id)
        if event.kind == 'actor_removed':
            if actor_key in self.active:
                self._end(actor_key, 'dead' if entity.removal_reason == 1 else 'removed',
                          packet.timestamp, packet_index, entity.removal_reason)
                self.revision += 1
            return
        if event.kind != 'actor_seen' or entity.class_id is None:
            return
        existing = self.active.get(actor_key)
        if existing and (existing['entity_key'] != entity.key or existing['class_id'] != entity.class_id):
            self._end(actor_key, 'appearance_or_class_changed', packet.timestamp, packet_index)
            existing = None
        if existing:
            if not math.isfinite(packet.timestamp) or packet.timestamp < existing['last_seen']:
                if 'timestamp_reversed' not in existing['quality_flags']:
                    existing['quality_flags'].append('timestamp_reversed')
            existing['last_seen'] = packet.timestamp
            return
        if len(self.records) >= self.max_records:
            self.saturated = True
            self.revision += 1
            return
        group_key = (*scope, entity.map_generation, entity.class_id)
        group = self.groups.setdefault(group_key, dict(capture_session=session, connection=packet.connection,
            map_generation=entity.map_generation, map_name=entity.map_name, class_id=entity.class_id,
            map_origin=entity.map_origin, map_evidence=deepcopy(entity.map_evidence),
            tracked_now=0, peak_tracked=0))
        previous = self.previous.get((*actor_key, entity.class_id))
        flags = ['assumed_boundary'] if ' [ASSUMED=' in packet.connection else []
        if not math.isfinite(packet.timestamp):
            flags.append('invalid_time')
        interval = None
        if previous and previous['end'] and previous['end']['kind'] in ('dead', 'removed'):
            start = previous['end']['timestamp']
            if (not flags and not previous['quality_flags'] and math.isfinite(start)
                    and math.isfinite(packet.timestamp) and packet.timestamp >= start):
                interval = dict(duration_ms=round((packet.timestamp - start) * 1000, 3),
                    basis='same_actor_after_' + previous['end']['kind'],
                    from_packet_index=previous['end']['packet_index'], to_packet_index=packet_index,
                    configured_respawn_confirmed=False)
        row = dict(group_key=group_key, entity_key=entity.key, capture_session=session,
            server_endpoint=deepcopy(entity.server_endpoint),
            connection=packet.connection, map_generation=entity.map_generation, actor_id=entity.actor_id,
            appearance=entity.appearance, class_id=entity.class_id, map_name=entity.map_name, name=entity.name,
            map_origin=entity.map_origin, map_evidence=deepcopy(entity.map_evidence),
            first_seen=packet.timestamp, last_seen=packet.timestamp, first_packet_index=packet_index,
            first_packet_id=packet.packet_id, first_position=dict(x=entity.x, y=entity.y), end=None,
            first_notification={0x9fe: 'spawn_notification', 0x9ff: 'first_idle', 0x9fd: 'first_moving'}[packet.packet_id],
            quality_flags=flags,
            reobservation_interval=interval)
        self.records.append(row)
        self.active[actor_key] = row
        self.previous[(*actor_key, entity.class_id)] = row
        group['tracked_now'] += 1
        group['peak_tracked'] = max(group['peak_tracked'], group['tracked_now'])
        self.revision += 1

    def snapshot(self):
        groups = []
        buckets = {}
        for row in self.records:
            buckets.setdefault(row['group_key'], []).append(row)
        for key, group in sorted(self.groups.items(), key=lambda item: min(actor_sort_key(row) for row in buckets[item[0]])):
            rows = buckets[key]
            intervals = [row['reobservation_interval'] for row in rows if row['reobservation_interval']]
            groups.append(dict(group, appearances=len(rows),
                unique_actor_ids=len({row['actor_id'] for row in rows}),
                deaths=sum(bool(row['end'] and row['end']['kind'] == 'dead') for row in rows),
                removals=sum(bool(row['end'] and row['end']['kind'] == 'removed') for row in rows),
                observed_reappearances=len(intervals), intervals=deepcopy(intervals),
                first_positions=[dict(row['first_position'], packet_index=row['first_packet_index']) for row in rows],
                configured_spawn_count=None, configured_respawn_ms=None))
        if self.world is not None:
            self.world_issue_count = self.world.issue_count
        return dict(schema_version=1, groups=groups, appearances=deepcopy(sorted(self.records, key=actor_sort_key)), saturated=self.saturated,
                    transport_quality='not_verified', server_spawn_settings_restored=False,
                    world_issue_count=self.world_issue_count)
