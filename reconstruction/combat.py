"""Direct MOB combat observations. Never infer base ATK/DEF or configured delays."""
from collections import Counter, deque
import math
from statistics import median

from reconstruction.decoder import Reader, ObservationError, decode_world_event

ATTACK_IDS = {0x8a, 0x2e1, 0x8c8}
DAMAGE_ACTIONS = {0, *range(4, 15)}


def decode_attack(packet):
    if packet.direction != 'RECV' or packet.packet_id not in ATTACK_IDS:
        return None
    r, pid = Reader(packet.raw), packet.packet_id
    legacy = pid == 0x8a
    modern = pid == 0x8c8
    r.take(0, 29 if legacy else 34 if modern else 33)
    kind_offset = 26 if legacy else 29 if modern else 28
    return dict(actor_id=r.number(2, 'I'), target_id=r.number(6, 'I'), server_tick=r.number(10, 'I'),
                source_delay=r.number(14, 'i'), target_delay=r.number(18, 'i'),
                damage=r.number(22, 'h' if legacy else 'i'),
                left_damage=r.number(kind_offset + 1, 'h' if legacy else 'i'),
                divisions=r.number(kind_offset - 2, 'h'), action=r.number(kind_offset, 'B'),
                sp_damage=r.number(26, 'B') if modern else 0)


def statistics(values):
    values = list(values)
    return dict(count=len(values), min=min(values) if values else None,
                median=median(values) if values else None, max=max(values) if values else None)


class CombatStore:
    def __init__(self, world, max_events=100000, max_entries=20000):
        self.world = world
        self.max_events, self.max_entries = max_events, max_entries
        self.events = []
        self.buckets = {}
        self.anchors = {}
        self.current_capture = -1
        self.packet_ordinal = 0
        self.revision = 0
        self.issue_count = 0
        self.issues = deque(maxlen=100)
        self.ignored_actions = 0
        self.unattributed = 0
        self.saturated = False

    def begin_capture(self, session):
        if session > self.current_capture:
            self.current_capture = session
            self.anchors.clear()
            self.revision += 1

    def apply(self, packet, session=0, packet_index=None):
        self.begin_capture(session)
        index = self.packet_ordinal if packet_index is None else packet_index
        self.packet_ordinal += 1
        if session != self.current_capture or packet.direction != 'RECV' or self.saturated:
            return
        reference = dict(packet_index=index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                         capture_session=session, connection=packet.connection, source=packet.source)
        records = []
        try:
            attack = decode_attack(packet)
            if attack is not None:
                if attack['action'] not in DAMAGE_ACTIONS:
                    self.ignored_actions += 1
                    self.revision += 1
                    return
                for role, actor in (('outgoing', attack['actor_id']), ('incoming', attack['target_id'])):
                    entity = self.world.find_current(packet, session, actor, 'MOB')
                    if entity:
                        counterparty = attack['target_id'] if role == 'outgoing' else attack['actor_id']
                        other = self.world.find_current(packet, session, counterparty)
                        records.append((entity, dict(attack, role=role, counterparty_id=counterparty,
                            counterparty_entity_key=other.key if other else None,
                            counterparty_class_id=other.class_id if other else None)))
                if not records:
                    self.unattributed += 1
                    self.revision += 1
                    return
            elif packet.packet_id in (0x9fe, 0x9ff, 0x9fd, 0x977, 0xa36):
                observation = decode_world_event(packet)
                entity = self.world.find_current(packet, session, observation.actor_id, 'MOB')
                if entity:
                    values = {key: observation.fields[key] for key in ('speed', 'hp', 'max_hp', 'hp_percent')
                              if key in observation.fields}
                    # 0A36 is a coarse five-percent step, not an exact HP ratio.
                    flags = []
                    if 'hp' in values and values['hp'] > values['max_hp']:
                        flags.append('hp_exceeds_max')
                    if 'hp' in values and (values['hp'] < 0 or values['max_hp'] <= 0):
                        flags.append('invalid_hp_values')
                    if values.get('hp_percent', 0) > 100:
                        flags.append('invalid_hp_percent')
                    records.append((entity, dict(values, role='state', flags=flags)))
            if not records:
                return
            new_keys = {(entity.key, entity.class_id) for entity, _ in records
                        if (entity.key, entity.class_id) not in self.buckets}
            if len(self.events) + len(records) > self.max_events or len(self.buckets) + len(new_keys) > self.max_entries:
                self.saturated = True
                raise ObservationError('Combat observation capacity reached; further observations disabled')
            for entity, fields in records:
                flags = fields.pop('flags', [])
                if not math.isfinite(packet.timestamp) or packet.timestamp < entity.first_seen:
                    flags.append('invalid_time')
                if ' [ASSUMED=' in packet.connection:
                    flags.append('assumed_boundary')
                if fields.get('sp_damage', 0) not in (0, 1):
                    flags.append('invalid_sp_damage_flag')
                record = dict(reference, entity_key=entity.key, class_id=entity.class_id,
                              name=entity.name, map_name=entity.map_name, flags=flags, interval_ms=None, interval_from_packet_index=None,
                              **fields)
                if record['role'] == 'outgoing':
                    key = (entity.key, entity.class_id, record['counterparty_id'], record['counterparty_entity_key'],
                           record['counterparty_class_id'], record['action'], record['sp_damage'])
                    previous = self.anchors.get(key)
                    if previous:
                        if packet.timestamp < previous['timestamp'] or not math.isfinite(previous['timestamp']):
                            flags.append('timestamp_reversed')
                        delta = (record['server_tick'] - previous['server_tick']) & 0xffffffff
                        if delta >= 0x80000000:
                            flags.append('tick_reversed_or_ambiguous')
                        if set(previous['flags']) & {'invalid_time', 'assumed_boundary', 'timestamp_reversed', 'tick_reversed_or_ambiguous'}:
                            flags.append('previous_observation_unreliable')
                        if 0 < delta < 0x80000000 and not flags:
                            record['interval_ms'] = delta
                            record['interval_from_packet_index'] = previous['packet_index']
                    self.anchors[key] = record
                self.events.append(record)
                self.buckets.setdefault((entity.key, entity.class_id), []).append(record)
            self.revision += 1
        except ObservationError as exc:
            self.anchors.clear()
            self.issue_count += 1
            self.issues.append(dict(reference, message=str(exc)))
            self.revision += 1

    def summaries(self, entity_key=None, aggregate=False):
        groups = {}
        for (identity, class_id), records in self.buckets.items():
            if entity_key is not None and entity_key != identity:
                continue
            key = class_id if aggregate else (identity, class_id)
            groups.setdefault(key, []).extend(records)
        result = []
        for records in groups.values():
            counts = Counter(record['role'] for record in records)
            stats = {}
            for role in ('outgoing', 'incoming'):
                selected = [record for record in records if record['role'] == role]
                hp_damage = [record for record in selected if record['sp_damage'] == 0
                             and record['damage'] >= 0 and record['left_damage'] >= 0]
                stats[role] = dict(
                    hp_damage_total=statistics(record['damage'] + record['left_damage'] for record in hp_damage),
                    special_damage_notifications=sum(record['damage'] < 0 or record['left_damage'] < 0 for record in selected),
                    sp_notifications=sum(record['sp_damage'] == 1 for record in selected),
                    unknown_sp_flag_notifications=sum(record['sp_damage'] not in (0, 1) for record in selected),
                    source_delay=statistics(record['source_delay'] for record in selected if record['source_delay'] >= 0),
                    target_delay=statistics(record['target_delay'] for record in selected if record['target_delay'] >= 0))
            contexts = {}
            for record in records:
                if record['role'] == 'state':
                    continue
                # Keep damage conditions and counterpart identities apart in the detailed report.
                context_key = (record['role'], record['capture_session'], record['connection'],
                               record['counterparty_id'], record['action'], record['sp_damage'],
                               record['entity_key'][2], record['counterparty_entity_key'], record['counterparty_class_id'])
                contexts.setdefault(context_key, []).append(record)
            context_rows = []
            for key, values in contexts.items():
                amounts = [v['damage'] + v['left_damage'] for v in values
                           if not v['sp_damage'] and v['damage'] >= 0 and v['left_damage'] >= 0]
                context_rows.append(dict(role=key[0], capture_session=key[1], connection=key[2], counterparty_id=key[3],
                    action=key[4], sp_damage=key[5], notifications=len(values), hp_damage=statistics(amounts),
                    map_generation=key[6], counterparty_entity_key=key[7], counterparty_class_id=key[8],
                    evidence=[v['packet_index'] for v in values]))
            samples = [dict(duration_ms=record['interval_ms'], from_packet_index=record['interval_from_packet_index'],
                            packet_index=record['packet_index'], entity_key=record['entity_key'],
                            counterparty_id=record['counterparty_id'], action=record['action'], sp_damage=record['sp_damage'],
                            counterparty_entity_key=record['counterparty_entity_key'],
                            counterparty_class_id=record['counterparty_class_id'])
                       for record in records if record['interval_ms'] is not None]
            state_records = [record for record in records if record['role'] == 'state']
            first = records[0]
            result.append(dict(class_id=first['class_id'], entity_key=None if aggregate else first['entity_key'],
                source_appearances=len({record['entity_key'] for record in records}), counts=dict(counts),
                damage=stats, damage_contexts=context_rows, outgoing_tick_interval=dict(
                    statistics(sample['duration_ms'] for sample in samples if sample['sp_damage'] == 0),
                    samples=[sample for sample in samples if sample['sp_damage'] == 0]),
                outgoing_sp_tick_interval=dict(statistics(sample['duration_ms'] for sample in samples if sample['sp_damage'] == 1),
                    samples=[sample for sample in samples if sample['sp_damage'] == 1]),
                speeds=sorted({record['speed'] for record in state_records if 'speed' in record}),
                observed_max_hp=sorted({record['max_hp'] for record in state_records
                                        if 'max_hp' in record and not set(record['flags']) & {'hp_exceeds_max', 'invalid_hp_values'}}),
                hp_samples=[dict(packet_index=record['packet_index'], hp=record.get('hp'), max_hp=record.get('max_hp'),
                                 hp_percent=record.get('hp_percent'), flags=record['flags']) for record in state_records
                            if 'hp' in record or 'hp_percent' in record],
                evidence=[record['packet_index'] for record in records], base_atk=None, base_def=None,
                configured_attack_delay_ms=None))
        return sorted(result, key=lambda row: (row['class_id'] if row['class_id'] is not None else -1, str(row['entity_key'])))

    def snapshot(self):
        return dict(schema_version=1, individual_performance=self.summaries(), class_performance=self.summaries(aggregate=True),
                    observations=self.events, issue_count=self.issue_count, issues=list(self.issues),
                    attack_packet_count=len({(record['capture_session'], record['packet_index']) for record in self.events
                                             if record['role'] != 'state'}),
                    ignored_actions=self.ignored_actions, unattributed_attack_notifications=self.unattributed,
                    saturated=self.saturated, transport_quality='not_verified')
