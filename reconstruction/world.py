"""Capture/connection/map/appearance scoped NPC and MOB state."""
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from copy import deepcopy

from reconstruction.decoder import ObservationError, Reader, WorldEvent, decode_world_event
from reconstruction.player import PlayerStore
from reconstruction.actor_appearance import OBSERVED_FIELDS
from reconstruction.actor_identity import server_endpoint, server_actor_observations, actor_sort_key

ACTOR_KINDS = {5: 'MOB', 6: 'NPC', 12: 'NPC'}


@dataclass
class Entity:
    capture_session: int
    connection: str
    map_generation: int
    actor_id: int
    appearance: int
    kind: str
    actor_type: int
    map_name: str | None
    first_seen: float
    last_seen: float
    name: str = ''
    class_id: int | None = None
    x: int | None = None
    y: int | None = None
    direction: int | None = None
    destination_x: int | None = None
    destination_y: int | None = None
    speed: int | None = None
    options: int | None = None
    hp: int | None = None
    max_hp: int | None = None
    hp_percent: int | None = None
    group_id: int | None = None
    title: str = ''
    appearance_data: dict = field(default_factory=dict)
    initial_display: dict = field(default_factory=dict)
    display_changes: list = field(default_factory=list)
    waitingrooms: list = field(default_factory=list)
    metadata_evidence: dict = field(default_factory=dict)
    active: bool = True
    state: str = 'visible'
    removal_reason: int | None = None
    observations: int = 0
    evidence: list = field(default_factory=list)
    field_issues: dict = field(default_factory=dict)
    flow_id: str = ''
    map_origin: str | None = None
    map_evidence: dict = field(default_factory=dict)
    server_endpoint: dict | None = None
    initial_options: int | None = None
    initial_state_evidence: dict = field(default_factory=dict)
    # showevent (0x0446) state; -1 = never observed. 9999 is a label/sentinel used for NPC判定.
    showevent_flag: int = -1
    showevent_kind: int = -1
    showevent_label: bool = False

    @property
    def key(self):
        return (self.capture_session, self.connection, self.map_generation, self.actor_id, self.appearance)


@dataclass
class Scene:
    generation: int = 0
    map_name: str | None = None
    map_origin: str | None = None
    map_evidence: dict = field(default_factory=dict)


class WorldStore:
    def __init__(self, max_entities=20000, max_pending_names=4096):
        self.entities = {}
        self.current = {}
        self.scenes = {}
        self.pending_names = OrderedDict()
        self.max_entities = max_entities
        self.max_pending_names = max_pending_names
        self.current_capture = -1
        self.packet_ordinal = 0
        self.capture_ordinals = {}
        self.revision = 0
        self.issue_count = 0
        self.evicted_names = 0
        self.issues = deque(maxlen=100)
        # Reuse player login/map binding without retaining inventory or combat data here.
        self.player_maps = PlayerStore()
        self.map_context = {}
        self.npc_initial_states = {}
        self.actor_history = OrderedDict()
        self.last_actor_observation = None
        self.last_showevent = None
        # Per MAP-generation actor showevent state for actors without an Entity spawn.
        self.showevent_state = OrderedDict()
        self.max_showevent_state = 20000
        self.display_observations = []
        self.display_dropped = 0

    def begin_capture(self, session):
        if session <= self.current_capture:
            return
        self.current_capture = session
        self.player_maps.begin_capture(session)
        self.map_context.clear()
        self.showevent_state.clear()
        self.last_showevent = None
        for entity in self.entities.values():
            if entity.active and entity.capture_session != session:
                entity.active = False
                entity.state = 'past_capture'
        self.revision += 1

    def _evidence(self, packet, session, index):
        return dict(capture_session=session, packet_index=index, packet_id=packet.packet_id,
                    capture_packet_index=self.capture_ordinals.get(session, 1) - 1,
                    timestamp=packet.timestamp, connection=packet.connection,
                    direction=packet.direction, source=packet.source)

    def _touch(self, entity, observation, evidence):
        entity.last_seen = observation.packet.timestamp
        entity.observations += 1
        entity.evidence.append(evidence)
        del entity.evidence[:-32]
        self.revision += 1

    @staticmethod
    def _fields(entity, fields, issues, evidence=None):
        if 'name' in issues:
            entity.metadata_evidence.pop('name_diagnostic', None)
        for name, value in fields.items():
            if name == 'name_diagnostic':
                entity.metadata_evidence['name_diagnostic'] = dict(deepcopy(value), evidence=deepcopy(evidence or {}))
                continue
            if name == 'name' and not value:
                continue
            if name == 'name':
                entity.metadata_evidence.pop('name_diagnostic', None)
            setattr(entity, name, value)
            if evidence and evidence['packet_id'] == 0xadf and name in ('group_id', 'title'):
                entity.metadata_evidence[name] = dict(evidence, value=value)
            entity.field_issues.pop(name, None)
        entity.field_issues.update(issues)

    def _issue(self, packet, session, index, message):
        self.issue_count += 1
        self.issues.append(dict(**self._evidence(packet, session, index), message=message))

    @staticmethod
    def _actor_history_key(entity):
        server = entity.server_endpoint
        namespace = ('server', server['ip'], server['port']) if server else ('connection', entity.connection)
        return (entity.capture_session, *namespace, entity.actor_id, entity.kind,
                entity.map_name if '@' in (entity.map_name or '') else None)

    def _appearance(self, entity, fields, evidence, *, reappeared=False, in_sight=True):
        key = self._actor_history_key(entity)
        previous = self.actor_history.get(key)
        incoming = {name:deepcopy(fields[name]) for name in OBSERVED_FIELDS if name in fields}
        if previous is None:
            if len(self.actor_history) >= self.max_entities:
                self.actor_history.popitem(last=False)
            initial = deepcopy(incoming)
            self.actor_history[key] = dict(initial=initial,current=deepcopy(incoming))
            entity.initial_display = deepcopy(initial)
            delta = {}
        else:
            entity.initial_display = deepcopy(previous['initial'])
            delta = {name:dict(before=deepcopy(previous['current'].get(name)),after=deepcopy(value))
                     for name,value in incoming.items() if previous['current'].get(name) != value}
            previous['current'].update(incoming)
        reappeared = reappeared or (previous is not None and entity.observations == 0)
        record = dict(evidence, actor_id=entity.actor_id, kind=entity.kind, npc_name=fields.get('name',entity.name),
            map_name=entity.map_name, map_generation=entity.map_generation, first_observation=previous is None, reappeared=reappeared,
            in_sight=in_sight and not reappeared, changes=delta,
            display=deepcopy(self.actor_history[key]['current']))
        self.last_actor_observation = record
        if delta:
            if len(self.display_observations) < 10000:
                self.display_observations.append(record)
                entity.display_changes.append(record)
                del entity.display_changes[:-32]
            else:
                self.display_dropped += 1
        return record

    def apply(self, packet, session=0, packet_index=None):
        self.begin_capture(session)
        self.last_actor_observation = None
        index = self.packet_ordinal if packet_index is None else packet_index
        self.packet_ordinal += 1
        self.capture_ordinals[session] = self.capture_ordinals.get(session, 0) + 1
        if packet.packet_id in (0x65, 0x71, 0x72, 0x436, 0x91, 0x92, 0x283):
            self._observe_player_map(packet, session, index)
        if packet.direction == 'RECV' and packet.packet_id == 0xd7:
            try:
                r = Reader(packet.raw)
                if not 18 <= len(packet.raw) <= 78 or r.number(2, 'H') != len(packet.raw):
                    raise ObservationError('Invalid waiting room packet length')
                actor = r.number(4, 'I')
                entity = self.find_current(packet, session, actor, kind='NPC')
                if entity:
                    room = dict(title=r.text(17), limit=r.number(12, 'H'), chat_id=r.number(8, 'I'),
                                users=r.number(14, 'H'), public=r.number(16, 'B'), evidence=self._evidence(packet, session, index))
                    if not any((old['title'], old['limit']) == (room['title'], room['limit']) for old in entity.waitingrooms):
                        if len(entity.waitingrooms) >= 32:
                            raise ObservationError('NPC waiting room observation capacity reached')
                        entity.waitingrooms.append(room)
                    self._touch(entity, WorldEvent('waitingroom', packet, actor, {}), room['evidence'])
                    return True
            except ObservationError as exc:
                self._issue(packet, session, index, str(exc))
            return False
        if packet.direction == 'RECV' and packet.packet_id == 0x446:
            return self._apply_showevent(packet, session, index)
        try:
            observation = decode_world_event(packet)
        except ObservationError as exc:
            self._issue(packet, session, index, str(exc))
            return False
        if observation is None:
            return False
        for name, message in observation.field_issues.items():
            self._issue(packet, session, index, f'{name}: {message}')
        scope = (session, packet.connection)
        scene = self.scenes.setdefault(scope, Scene())
        evidence = self._evidence(packet, session, index)
        if packet.packet_id==0x1b0:
            evidence['classchange_kind']=Reader(packet.raw).number(6,'B')
        if observation.field_issues:
            evidence['field_issues'] = dict(observation.field_issues)
        if 'name_diagnostic' in observation.fields:
            evidence['name_diagnostic'] = deepcopy(observation.fields['name_diagnostic'])
        if observation.kind == 'map_changed':
            for entity in self.entities.values():
                if entity.capture_session == session and entity.connection == packet.connection and entity.active:
                    entity.active = False
                    entity.state = 'previous_map'
                    self._touch(entity, observation, evidence)
            scene.generation += 1
            scene.map_name = observation.fields['map_name'] or None
            scene.map_origin = 'player_current_map' if scene.map_name else None
            scene.map_evidence = deepcopy(self.map_context.get((session, packet.flow_id or packet.connection), {}))
            for identity in list(self.pending_names):
                if identity[:2] == scope:
                    self.pending_names.pop(identity)
            self.revision += 1
            return True
        identity = (*scope, scene.generation, observation.actor_id)
        entity_key = self.current.get(identity)
        entity = self.entities.get(entity_key)
        past_continuation = (entity is not None and session < self.current_capture
                             and entity.state == 'past_capture')
        if observation.kind == 'actor_seen':
            if scene.map_name is None:
                key = (session, packet.flow_id or packet.connection)
                state = self.player_maps.states.get(key)
                if state is not None and state.map_name:
                    scene.map_name = state.map_name
                    scene.map_origin = 'player_current_map'
                    scene.map_evidence = deepcopy(self.map_context.get(key, {}))
            actor_type = observation.fields['actor_type']
            kind = ACTOR_KINDS.get(actor_type)
            if kind is None:
                self.pending_names.pop(identity, None)
                if entity and entity.active:
                    entity.active = False
                    entity.state = 'replaced'
                    self._touch(entity, observation, evidence)
                    return True
                return False
            reappeared = entity is not None and not entity.active
            if entity is None or (not entity.active and not past_continuation) or entity.kind != kind:
                if len(self.entities) >= self.max_entities:
                    self._issue(packet, session, index, 'Entity capacity reached; new actor not added')
                    return False
                previous = entity
                if previous and previous.active:
                    previous.active = False
                    previous.state = 'replaced'
                entity = Entity(session, packet.connection, scene.generation, observation.actor_id,
                                1 if previous is None else previous.appearance + 1,
                                kind, actor_type, scene.map_name, packet.timestamp, packet.timestamp)
                entity.flow_id = packet.flow_id or packet.connection
                entity.server_endpoint = server_endpoint(packet)
                entity.map_origin = scene.map_origin
                entity.map_evidence = deepcopy(scene.map_evidence)
                self.entities[entity.key] = entity
                self.current[identity] = entity.key
                pending = self.pending_names.pop(identity, None)
                if pending:
                    fields, issues, reference = pending
                    self._fields(entity, fields, issues, reference)
                    entity.evidence.append(reference)
            self._appearance(entity, observation.fields, evidence, reappeared=reappeared)
            self._fields(entity, observation.fields, observation.field_issues, evidence)
            if entity.kind == 'NPC' and type(observation.fields.get('options')) is int:
                initial_key = self._actor_history_key(entity)
                initial = self.npc_initial_states.setdefault(initial_key,
                    dict(options=observation.fields['options'], evidence=deepcopy(evidence)))
                entity.initial_options = initial['options']
                entity.initial_state_evidence = deepcopy(initial['evidence'])
            if session != self.current_capture:
                entity.active = False
                entity.state = 'past_capture'
            self._touch(entity, observation, evidence)
            return True
        if observation.kind == 'actor_removed':
            self.pending_names.pop(identity, None)
            if entity is None or (not entity.active and not past_continuation):
                return False
            entity.active = False
            entity.removal_reason = observation.fields['reason']
            entity.state = 'dead' if entity.removal_reason == 1 else 'removed'
            self._touch(entity, observation, evidence)
            return True
        if observation.kind == 'actor_name' and entity is None:
            self.pending_names[identity] = (observation.fields, observation.field_issues, evidence)
            self.pending_names.move_to_end(identity)
            if len(self.pending_names) > self.max_pending_names:
                self.pending_names.popitem(last=False)
                self.evicted_names += 1
            return False
        if entity is not None and observation.kind == 'actor_update' and (entity.active or 'class_id' in observation.fields):
            self._appearance(entity, observation.fields, evidence, in_sight=entity.active)
            if not entity.active and 'class_id' in observation.fields:
                self._fields(entity, observation.fields, observation.field_issues, evidence)
                self._touch(entity,observation,evidence)
                return True
        if entity is None or (not entity.active and not past_continuation):
            return False
        self._fields(entity, observation.fields, observation.field_issues, evidence)
        self._touch(entity, observation, evidence)
        return True

    def _observe_player_map(self, packet, session, index):
        values = self.player_maps.apply(packet, session=session, packet_index=index)
        if values is None or values['event_kind'] == 'error':
            if values is not None and packet.packet_id not in (0x91, 0x92):
                self._issue(packet, session, index, 'Player map context: ' + values['observation_error'])
            return
        evidence = self._evidence(packet, session, index)
        kind = values['event_kind']
        key = (session, packet.flow_id or packet.connection)
        state = self.player_maps.states.get(key)
        if kind in ('login', 'map', 'account'):
            if kind == 'account' and state is not None and state.map_name and key in self.map_context:
                return
            self.map_context.pop(key, None)
            if state is not None and state.map_name:
                reference = dict(basis='player_current_map', flow_id=key[1], map_name=state.map_name,
                                 observation=evidence)
                if kind == 'login':
                    reference['character_id'] = state.character_id
                    reference['map_hint'] = deepcopy(state.evidence.get('map_hint'))
                self.map_context[key] = reference
        for expired in set(self.map_context) - self.player_maps.states.keys():
            self.map_context.pop(expired)

    def records(self, kind=None, active_only=False):
        return sorted((entity for entity in self.entities.values()
                       if (kind is None or entity.kind == kind) and (not active_only or entity.active)),
                      key=actor_sort_key)

    def _apply_showevent(self, packet, session, index):
        """Track 0x0446 showevent_flag per actor. Does not invent spawn Entities."""
        self.last_showevent = None
        try:
            if len(packet.raw) != 14:
                raise ObservationError('Invalid showevent packet length')
            r = Reader(packet.raw)
            actor = r.number(2, 'I')
            x = r.number(6, 'H')
            y = r.number(8, 'H')
            state = r.number(10, 'H')
            kind = r.number(12, 'H')
        except ObservationError as exc:
            self._issue(packet, session, index, str(exc))
            return False
        scope = (session, packet.connection)
        scene = self.scenes.setdefault(scope, Scene())
        identity = (*scope, scene.generation, actor)
        previous = self.showevent_state.get(identity, (-1, -1))
        current = (state, kind)
        changed = previous != current
        self.showevent_state[identity] = current
        self.showevent_state.move_to_end(identity)
        while len(self.showevent_state) > self.max_showevent_state:
            self.showevent_state.popitem(last=False)
        entity = self.find_current(packet, session, actor, kind='NPC', active_only=False)
        has_spawn = entity is not None
        name = entity.name if entity and entity.name else ''
        if entity is not None:
            entity.showevent_flag = state
            entity.showevent_kind = kind
            if state == 9999:
                entity.showevent_label = True
            evidence = self._evidence(packet, session, index)
            if changed:
                self._touch(entity, WorldEvent('showevent', packet, actor,
                                               {'state': state, 'kind': kind, 'x': x, 'y': y}), evidence)
        # 9999 without spawn: observation-log label only — never create a placement Entity.
        self.last_showevent = dict(
            actor_id=actor, state=state, kind=kind, x=x, y=y, changed=changed,
            has_spawn=has_spawn, npc_name=name, label=(state == 9999))
        self.revision += 1
        return True

    def find_current(self, packet, session, actor_id, kind=None, active_only=True):
        scope = (session, packet.connection)
        scene = self.scenes.get(scope)
        if scene is None:
            return None
        key = self.current.get((*scope, scene.generation, actor_id))
        entity = self.entities.get(key)
        return entity if (entity is not None and (not active_only or entity.active)
                          and (kind is None or entity.kind == kind)) else None

    def snapshot(self, kind=None, active_only=False):
        records = self.records(kind, active_only)
        return dict(schema=1, decoder='maria-09xx-v1', display_observations=deepcopy(self.display_observations), display_dropped=self.display_dropped, kind=kind, active_only=active_only,
                    entities=[asdict(entity) for entity in records],
                    server_actor_observations=server_actor_observations(records),
                    issue_count=self.issue_count, issues=list(self.issues),
                    evicted_pending_names=self.evicted_names,
                    note='Map names use the same-flow player current map, including character-bound login hints; unknown maps remain unknown.')
