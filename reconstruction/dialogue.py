"""Observed dialogue paths. No inference of unseen conditions or timer commands."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field

from reconstruction.touch import (context as touch_context, is_touch, TOUCH_CLASSES, can_trigger,
                                  MAX_TOUCH_RADIUS, priority, compare_conversation_trials)
from reconstruction.decoder import ObservationError, Reader, decode_world_event
from reconstruction.quests import decode_quest, QUEST_PACKET_IDS
from reconstruction.conversation_actions import status_event, STATUS_IDS
from reconstruction.speech_origin import SpeechOrigin, payload as speech_payload, index_player_notifications
from reconstruction.progress import ProgressTrace
from reconstruction.script_commands import ScriptCommandStore
from reconstruction.actor_appearance import declaration_class

WALK_SEND_IDS = {0x85, 0x35f}
PRESENTATION_ACTOR_OFFSETS = {0xc0: 2, 0x19b: 2, 0x1f3: 2, 0x1d3: 31,
                              0x1b0: 2, 0x9d1: 2, 0x144: 2, 0x8b3: 4, 0x8d: 4, 0x2c1: 4, 0xb0d: 2, 0x284: 2,
                              0x446: 2, 0xa3b: 4, 0x8ff: 2, 0x984: 2, 0x29b: 2}
EXTERNAL_PRESENTATION_IDS = {0xc0, 0x19b, 0x1f3, 0x1d3, 0x8b3, 0x8d, 0x2c1, 0xb0d, 0x284, 0x446, 0xa3b,
                             0x8ff, 0x984, 0x29b}
DIALOGUE_LAYOUT_IDS = {0xba1, 0xba2, 0xba3, 0xbb5}
DIALOGUE_LAYOUT_KINDS = {'dialogue_size', 'dialogue_position', 'dialogue_alignment'}


def decode_dialogue(packet):
    r, pid = Reader(packet.raw), packet.packet_id
    if packet.direction == 'SEND':
        kinds = {0x90: 'open', 0xb8: 'choice', 0xb9: 'continue', 0x146: 'dismiss',
                 0x143: 'number_reply', 0x1d5: 'text_reply'}
    else:
        kinds = {0xb4: 'mes', 0x972: 'mes', 0xb5: 'next', 0x973: 'next',
                 0xb6: 'close', 0x8d6: 'clear', 0xb7: 'menu',
                 0x142: 'number', 0x1d4: 'text', 0x1b3: 'cutin',
                 0xc0: 'emotion', 0x1d3: 'sound', 0x19b: 'effect', 0x1f3: 'effect', 0x1b0: 'classchange',
                 0x2f0: 'progressbar', 0x9d1: 'progressbar', 0x7fe: 'music', 0xb8c: 'music',
                 0x144: 'viewpoint', 0x8b3: 'overhead', 0x8d: 'unittalk', 0x2c1: 'colored_speech',
                 0xb0d: 'effect_remove', 0x284: 'effect_value',
                 0x446: 'event_marker', 0xa3b: 'hat_effect', 0xa24: 'achievement',
                 0xab9: 'item_preview', 0xb13: 'item_preview',
                 0x1d6: 'map_property', 0x99b: 'map_property', 0x2e7: 'map_property',
                 0x8ff: 'status_enter', 0x984: 'status_enter', 0x29b: 'mercenary',
                 0x8e2: 'navigation_active'}
        kinds.update({0x9a: 'announcement', 0x1c3: 'announcement', 0x40c: 'announcement'})
    if packet.direction == 'RECV' and pid in DIALOGUE_LAYOUT_IDS:
        expected = 3 if pid == 0xba1 else 10
        if len(packet.raw) != expected:
            raise ObservationError('Dialogue layout length does not match supported layout')
        if pid == 0xba1:
            return 'dialogue_alignment', None, dict(alignment=r.number(2, 'B'))
        if pid == 0xba2:
            return 'dialogue_size', None, dict(height=r.number(2, 'I'), width=r.number(6, 'I'))
        return 'dialogue_position', None, dict(x=r.number(2, 'I'), y=r.number(6, 'I'))
    if packet.direction == 'RECV' and pid == 0x192:
        if len(packet.raw) != 24:
            raise ObservationError('Map cell length does not match supported layout')
        return 'mapcell', None, dict(x=r.number(2, 'H'), y=r.number(4, 'H'),
            cell_type=r.number(6, 'H'), map_name=r.text(8, 16))
    kind = kinds.get(pid)
    if kind is None:
        return None
    if kind == 'effect_value':
        if len(packet.raw) != 14:
            raise ObservationError('Valued effect length does not match supported layout')
        return kind, r.number(2, 'I'), dict(effect_id=r.number(6, 'I'), value=r.number(10, 'I'))
    if kind == 'event_marker':
        if len(packet.raw) != 14:
            raise ObservationError('Event marker length does not match supported layout')
        return kind, r.number(2, 'I'), dict(x=r.number(6, 'H'), y=r.number(8, 'H'),
                                           state=r.number(10, 'H'), kind=r.number(12, 'H'))
    if kind == 'hat_effect':
        # Display JSON: actor_id@4, enabled@8, effect_id@9. PacketLength -1; known body is 11 bytes.
        if len(packet.raw) != 11 or r.number(2, 'H') != 11:
            raise ObservationError('Hat effect length does not match supported layout')
        return kind, r.number(4, 'I'), dict(enabled=r.number(8, 'B'), effect_id=r.number(9, 'H'))
    if kind == 'achievement':
        # PacketLength 66. Display JSON only documents achievement_id@16; other bytes stay opaque.
        if len(packet.raw) != 66:
            raise ObservationError('Achievement length does not match supported layout')
        return kind, None, dict(achievement_id=r.number(16, 'I'))
    if kind == 'item_preview':
        # PacketLength 0AB9=47 / 0B13=48. Display JSON only documents index@2 (add -2); rest opaque.
        expected = 47 if pid == 0xab9 else 48
        if len(packet.raw) != expected:
            raise ObservationError('Item preview length does not match supported layout')
        index = r.number(2, 'H') - 2
        if not 0 <= index <= 65533:
            raise ObservationError('Item preview index is out of supported range')
        return kind, None, dict(index=index)
    if kind == 'navigation_active':
        # PACKET_ZC_NAVIGATION_ACTIVE / PacketLength 27. No actor; client Navigation UI only.
        if len(packet.raw) != 27:
            raise ObservationError('Navigation-active length does not match supported layout')
        return kind, None, dict(
            type=r.number(2, 'B'), set_type=r.number(3, 'B'), hide=r.number(4, 'B'),
            map_name=r.text(5, 16), x=r.number(21, 'h'), y=r.number(23, 'h'),
            spr_index=r.number(25, 'h'))
    if kind == 'map_property':
        # 01D6=4 type / 099B=8 type+flags / 02E7=-1 PACKET_ZC_MAPPROPERTY sample len 33.
        # No actor; map属性のみ。NPC本文命令へは出さない。
        if pid == 0x2e7:
            from reconstruction.zc_mapproperty import decode_zc_mapproperty_table, load_default_catalogs
            try:
                zc_symbols, _catalog = load_default_catalogs()
                decoded = decode_zc_mapproperty_table(packet.raw, zc_symbols)
            except ValueError as exc:
                raise ObservationError(str(exc)) from exc
            return kind, None, dict(
                kind=decoded['type_id'], layout='zc_mapproperty_table',
                table=decoded['table'], nonzero_properties=decoded['nonzero_properties'])
        expected = 4 if pid == 0x1d6 else 8
        if len(packet.raw) != expected:
            raise ObservationError('Map property length does not match supported layout')
        fields = dict(kind=r.number(2, 'H'))
        if pid == 0x99b:
            fields['flags'] = r.number(4, 'I')
        return kind, None, fields
    if kind == 'status_enter':
        # PacketLength 08FF=24 / 0984=28. Separate from STATUS_IDS (0196/043F/0983); never sc_start.
        expected = 24 if pid == 0x8ff else 28
        if len(packet.raw) != expected:
            raise ObservationError('Status-enter length does not match supported layout')
        actor = r.number(2, 'I')
        fields = dict(effect_id=r.number(6, 'H'), remaining_ms=r.number(8, 'I'),
                      value1=r.number(12 if pid == 0x8ff else 16, 'I'),
                      value2=r.number(16 if pid == 0x8ff else 20, 'I'),
                      value3=r.number(20 if pid == 0x8ff else 24, 'I'))
        if pid == 0x984:
            fields['tick'] = r.number(12, 'I')
        return kind, actor, fields
    if kind == 'mercenary':
        # PacketLength 80. Display: actor_id@2, name@22 len24, duration@64. Other bytes opaque.
        if len(packet.raw) != 80:
            raise ObservationError('Mercenary length does not match supported layout')
        return kind, r.number(2, 'I'), dict(name=r.text(22, 24), duration=r.number(64, 'I'))
    if kind == 'announcement':
        offset = 4 if pid == 0x9a else 16
        if (not offset + 1 <= len(packet.raw) <= 65535
                or r.number(2, 'H') != len(packet.raw) or packet.raw[-1] != 0):
            raise ObservationError('Announcement length or text terminator does not match supported layout')
        if pid == 0x9a:
            prefix = packet.raw[4:8]
            known_prefix = prefix in (b'blue', b'ssss', b'tool')
            return kind, None, dict(text=r.text(8 if known_prefix else 4),
                                    broadcast_prefix=prefix.decode('ascii') if known_prefix else None)
        return kind, None, dict(text=r.text(16), color=r.number(4, 'I'), font_type=r.number(8, 'H'),
            font_size=r.number(10, 'H'), font_align=r.number(12, 'H'), font_y=r.number(14, 'H'))
    if kind in ('overhead', 'unittalk'):
        if not 9 <= len(packet.raw) <= 65535 or r.number(2, 'H') != len(packet.raw):
            raise ObservationError('Overhead message total length does not match raw bytes')
        return kind, r.number(4, 'I'), dict(text=r.text(8))
    if kind == 'colored_speech':
        # PacketLength -1. Display JSON: actor_id@4, color@8, text@12. Do not treat as unittalk.
        if not 13 <= len(packet.raw) <= 65535 or r.number(2, 'H') != len(packet.raw):
            raise ObservationError('Colored speech total length does not match raw bytes')
        return kind, r.number(4, 'I'), dict(color=r.number(8, 'I'), text=r.text(12))
    if kind == 'viewpoint':
        if len(packet.raw) != 23:
            raise ObservationError('Viewpoint packet length does not match supported layout')
        return kind, r.number(2, 'I'), dict(kind=r.number(6, 'I'), x=r.number(10, 'I'),
            y=r.number(14, 'I'), marker_id=r.number(18, 'B'), color=r.number(19, 'I'))
    if kind == 'music':
        if pid == 0x7fe:
            if len(packet.raw) != 26:
                raise ObservationError('Music packet length does not match supported layout')
            return kind, None, dict(music=r.text(2, 24), mode=None)
        if not 6 <= len(packet.raw) <= 65535 or r.number(2, 'H') != len(packet.raw):
            raise ObservationError('Typed music total length does not match raw bytes')
        return kind, None, dict(music=r.text(5), mode=r.number(4, 'B'))
    if kind == 'progressbar':
        targeted = pid == 0x9d1
        if len(packet.raw) != (14 if targeted else 10):
            raise ObservationError('Progress bar packet length does not match supported layout')
        offset = 6 if targeted else 2
        return kind, r.number(2, 'I') if targeted else None, dict(
            color=r.number(offset, 'I'), seconds=r.number(offset + 4, 'I'))
    if kind == 'classchange':
        if len(packet.raw) != 11:
            raise ObservationError('Class change packet length does not match supported layout')
        return kind, r.number(2, 'I'), dict(class_id=r.number(7, 'I'), kind=r.number(6, 'B'))
    if kind in ('emotion', 'effect', 'effect_remove', 'sound'):
        expected = {'emotion': 7, 'effect': 10, 'effect_remove': 10, 'sound': 35}[kind]
        if len(packet.raw) != expected:
            raise ObservationError('NPC presentation packet length does not match supported layout')
        if kind == 'emotion':
            return kind, r.number(2, 'I'), dict(value=r.number(6, 'B'))
        if kind in ('effect', 'effect_remove'):
            return kind, r.number(2, 'I'), dict(value=r.number(6, 'I'))
        if r.number(26, 'B') not in (0, 1, 2):
            raise ObservationError('Unsupported NPC sound mode')
        return kind, r.number(31, 'I'), dict(sound=r.text(2, 24), mode=r.number(26, 'B'),
                                          interval=r.number(27, 'I'))
    variable = pid in (0xb4, 0x972, 0xb7, 0x1d5)
    if variable and r.number(2, 'H') != len(packet.raw):
        raise ObservationError('Dialogue total length does not match raw bytes')
    if kind == 'cutin':
        return kind, None, dict(image=r.text(2, 64), position=r.number(66, 'B'))
    actor = r.number(4 if variable else 2, 'I')
    fields = {}
    if kind in ('mes', 'menu', 'text_reply'):
        fields['text'] = r.text(9 if pid == 0x972 else 8)
    if kind == 'menu':
        options = fields['text'].split(':')
        # Trailing empty slots cannot change earlier reply numbers. Preserve the
        # original text above; internal empty slots remain unsupported.
        while options and not options[-1]:
            options.pop()
        if not options or len(options) > 254 or any(not option for option in options):
            raise ObservationError('Unsupported empty or oversized dialogue menu')
        fields['options'] = options
    if kind == 'choice':
        fields['value'] = r.number(6, 'B')
    if kind == 'number_reply':
        fields['value'] = r.number(6, 'i')
    if kind == 'open':
        fields['type'] = r.number(6, 'B')
    if pid in (0x972, 0x973):
        fields['type'] = r.number(8 if pid == 0x972 else 6, 'B')
    return kind, actor, fields


@dataclass
class Conversation:
    id: int
    capture_session: int
    flow_id: str
    actor_id: int
    started: float
    observed_open: bool
    status: str = 'observing'
    steps: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    npc: dict = field(default_factory=dict)
    termination: dict = field(default_factory=dict)
    parallel_presentations: list = field(default_factory=list)
    resource_observations: list = field(default_factory=list)
    external_presentations: list = field(default_factory=list)
    quest_info_links: list = field(default_factory=list)
    late_replies: list = field(default_factory=list)
    actions: list = field(default_factory=list)


class DialogueStore:
    def __init__(self, max_sessions=2000, max_steps=100000, world=None, max_presentations=10000):
        self.world = world
        self.source_refs = {}
        self.sessions = []
        self.active = {}
        self.max_sessions, self.max_steps = max_sessions, max_steps
        self.step_count = 0
        self.packet_ordinal = 0
        self.revision = 0
        self.current_capture = -1
        self.issues = deque(maxlen=100)
        self.issue_count = 0
        self.map_arrival_anchors = []
        self.map_anchor_dropped = 0
        self.presentation_observations = []
        self.max_presentations = max_presentations
        self.presentation_dropped = 0
        self.resource_count = 0
        self.quest_observations, self.quest_dropped = [], 0
        self.commands = ScriptCommandStore()
        self.speech = SpeechOrigin()
        self.progress = ProgressTrace()
        self.action_count = 0
        self.action_dropped = 0
        self.visibility_states = {}
        self.touch_warp_inferences = deque(maxlen=2000)
        self.touch_inference_dropped = 0
        self.touch_positions = {}
        self.pending_walk_sends = {}
        self.shop_recent = {}
        self.close_pending, self.after_close = {}, {}
        self.timeout_closed = {}
        self.late_reply_count, self.late_reply_dropped = 0, 0

    def shop_context(self, packet, session):
        key = (session, packet.flow_id or packet.connection)
        if key in self.active:
            return self.active[key]
        recent = self.shop_recent.get(key)
        if recent and session == self.current_capture and 0 <= packet.timestamp - recent[0] <= 2:
            return recent[1]
        return None

    def _retain_resources(self, packet, session, index, conversation, values):
        if not conversation or session != self.current_capture or packet.direction != 'RECV' or not values:
            return
        kind = values.get('event_kind')
        fields = None
        if kind == 'zeny':
            if values['delta_known'] and values['delta'] == 0:
                return
            fields = dict(value=values['zeny'], delta=values['delta'], delta_known=values['delta_known'])
        elif kind in ('item_gain', 'item_loss'):
            if kind == 'item_gain' and values['result'] != 0:
                return
            fields = {key: values[key] for key in ('item_id', 'amount', 'index')}
        elif kind == 'map':
            fields = {key: values[key] for key in ('map_name', 'x', 'y')}
        elif kind in ('quest_add', 'quest_delete', 'quest_state', 'quest_count'):
            fields = deepcopy(values['quest_fields'])
        if fields is None:
            return
        if (self.resource_count >= 10000 or len(conversation.resource_observations) >= 512
                or len(conversation.steps) + len(conversation.parallel_presentations)
                   + len(conversation.resource_observations) + len(conversation.external_presentations) + len(conversation.actions) >= 2048):
            self._issue(packet, index, 'Conversation resource observation capacity reached')
            if not any(row['message'] == 'Resource observation capacity reached' for row in conversation.issues):
                conversation.issues.append(dict(packet_index=index, message='Resource observation capacity reached'))
            return
        conversation.resource_observations.append(dict(kind=kind, fields=fields, cause_confirmed=False,
            adoption_confirmed=False,
            after_step_index=len(conversation.steps) - 1,
            packet_index=index, packet_id=packet.packet_id, timestamp=packet.timestamp,
            connection=packet.connection, source=packet.source, direction=packet.direction,
            capture_session=session, flow_id=packet.flow_id or packet.connection))
        self.resource_count += 1
        self.revision += 1

    ADOPTABLE_EXTERNAL_KINDS = frozenset(
        ('emotion', 'effect', 'effect_remove', 'overhead', 'unittalk', 'event_marker'))

    def set_resource_adoption(self, conversation, packet_index, confirmed):
        """Explicit per-row adoption for command candidates. Never flips cause_confirmed."""
        if confirmed is not True and confirmed is not False:
            raise ValueError('Resource adoption confirmation must be a boolean')
        for row in conversation.resource_observations:
            if row['packet_index'] != packet_index:
                continue
            if row['kind'].startswith('quest_'):
                raise ValueError('Quest resources use the existing setquest path')
            if row['kind'] not in ('zeny', 'item_gain', 'item_loss', 'map'):
                raise ValueError('Unsupported resource kind for adoption')
            row['adoption_confirmed'] = confirmed
            self.revision += 1
            return row
        raise ValueError('Resource observation not found')

    def set_external_adoption(self, conversation, packet_index, confirmed):
        """Explicit per-row adoption for external NPC candidates. Never flips cause_confirmed."""
        if confirmed is not True and confirmed is not False:
            raise ValueError('External adoption confirmation must be a boolean')
        for row in conversation.external_presentations:
            if row['packet_index'] != packet_index:
                continue
            if row.get('context') != 'external_candidate' or row.get('entity_kind') != 'NPC':
                raise ValueError('Only NPC external candidates can be adopted')
            if row['kind'] not in self.ADOPTABLE_EXTERNAL_KINDS:
                raise ValueError('Unsupported external kind for adoption')
            if not row['npc'].get('name'):
                raise ValueError('External candidate without NPC name cannot be adopted')
            row['adoption_confirmed'] = confirmed
            self.revision += 1
            return row
        raise ValueError('External presentation not found')

    def _self_actor(self, packet, session):
        state = self.world.player_maps.states.get((session, packet.flow_id or packet.connection)) if self.world else None
        return state.actor_id if state else None

    def _retain_presentation(self, packet, session, index, actor, context, conversation=None, prompt_index=None, decoded=None, player_conversation=None):
        try:
            kind, _, fields = decoded if decoded is not None else decode_dialogue(packet)
        except ObservationError as exc:
            self._issue(packet, index, str(exc))
            if conversation:
                conversation.issues.append(dict(packet_index=index, message='Invalid parallel presentation'))
            return
        if (len(self.presentation_observations) >= self.max_presentations or
                (conversation and len(conversation.steps) + len(conversation.parallel_presentations)
                 + len(conversation.resource_observations) + len(conversation.external_presentations) + len(conversation.actions) >= 2048)):
            self.presentation_dropped += 1
            self._issue(packet, index, 'Presentation observation capacity reached')
            if conversation and not any(row['message'] == 'Parallel presentation capacity reached'
                                        for row in conversation.issues):
                conversation.issues.append(dict(packet_index=index, message='Parallel presentation capacity reached'))
            return
        record = dict(kind=kind, fields=fields, capture_session=session, flow_id=packet.flow_id or packet.connection,
                      actor_id=actor, context=context, prompt_step_index=prompt_index,
                      target_observed=actor is not None,
                      timestamp=packet.timestamp, packet_index=index, packet_id=packet.packet_id,
                      direction=packet.direction, connection=packet.connection, source=packet.source)
        entity = self.world.find_current(packet, session, actor) if self.world else None
        record['entity_kind'] = entity.kind if entity else 'unresolved'
        record['npc'] = ({name: getattr(entity, name) for name in
                          ('name', 'map_name', 'class_id', 'x', 'y', 'direction', 'appearance', 'map_generation')}
                         if entity and entity.kind == 'NPC' else {})
        if kind in ('unittalk', 'player_chat', 'overhead', 'colored_speech'):
            self_actor = self._self_actor(packet, session)
            record['speech_origin'] = self.speech.received(packet, session, index, actor, self_actor)
            if self_actor is not None and actor == self_actor:
                record['entity_kind'] = 'PLAYER'
                record['npc'] = {}
        scene = self.world.scenes.get((session, packet.connection)) if self.world else None
        if scene and scene.map_name:
            record['instance_mode'] = '@' in scene.map_name
            record['map_context'] = dict(map_name=scene.map_name, map_generation=scene.generation)
        if player_conversation is not None and kind == 'overhead' and record['entity_kind'] == 'PLAYER':
            record.update(association_basis='active_dialogue_same_flow_player_notification',
                conversation_id=player_conversation.id,conversation_actor_id=player_conversation.actor_id,
                after_step_index=len(player_conversation.steps)-1,cause_confirmed=False)
        if player_conversation is not None and kind in DIALOGUE_LAYOUT_KINDS:
            # This is temporal context, not proof of the command's caller.
            record.update(association_basis='same_flow_active_dialogue_layout',
                conversation_id=player_conversation.id, conversation_actor_id=player_conversation.actor_id,
                conversation_start_packet_index=(player_conversation.steps[0]['packet_index']
                    if player_conversation.steps else None),
                after_step_index=len(player_conversation.steps)-1, cause_confirmed=False)
        if kind == 'announcement' and conversation:
            record['association_basis'] = 'active_dialogue_same_flow'
            record['conversation_id'] = conversation.id
            record['npc'] = deepcopy(conversation.npc)
        if kind == 'map_property':
            from reconstruction.zc_mapproperty import build_map_property_manual_review
            map_name = (record.get('map_context') or {}).get('map_name')
            if map_name is None and self.world is not None:
                state = self.world.player_maps.states.get((session, packet.flow_id or packet.connection))
                if state is not None and state.map_name:
                    map_name = state.map_name
                    record['map_context'] = dict(
                        map_name=map_name, map_generation=getattr(state, 'map_generation', None),
                        basis='player_current_map_fallback')
                    record['instance_mode'] = '@' in map_name
            record['manual_review'] = build_map_property_manual_review(fields, map_name)
        if context == 'external_candidate' and conversation:
            origin = self.world.find_current(packet, session, conversation.actor_id, kind='NPC')
            record.update(association_basis='same_flow_active_dialogue_external_target',
                conversation_id=conversation.id, conversation_actor_id=conversation.actor_id,
                conversation_entity_key=list(origin.key), target_entity_key=list(entity.key),
                cause_confirmed=False, adoption_confirmed=False,
                after_step_index=len(conversation.steps) - 1)
        self.presentation_observations.append(record)
        if conversation:
            if context == 'external_candidate':
                conversation.external_presentations.append(record)
            else:
                conversation.parallel_presentations.append(record)
            if kind == 'event_marker':
                from reconstruction.quest_info import associate_quest_showevent
                associate_quest_showevent(conversation, record)
        self.revision += 1

    def _retain_action(self, packet, session, index, conversation, kind, fields):
        if (not conversation.steps or self.action_count >= 10000 or len(conversation.actions) >= 512
                or len(conversation.steps) + len(conversation.actions) + len(conversation.parallel_presentations)
                   + len(conversation.external_presentations) + len(conversation.resource_observations) >= 2048):
            self.action_dropped += 1
            self._issue(packet, index, 'Conversation action capacity reached')
            conversation.issues.append(dict(packet_index=index, message='Conversation action capacity reached'))
            return
        conversation.actions.append(dict(kind=kind, fields=deepcopy(fields), capture_session=session,
            flow_id=packet.flow_id or packet.connection, packet_index=index, packet_id=packet.packet_id,
            timestamp=packet.timestamp, direction=packet.direction, connection=packet.connection,
            source=packet.source, after_step_index=len(conversation.steps) - 1, cause_confirmed=False))
        self.action_count += 1
        self.revision += 1
        return conversation.actions[-1]

    def _observe_actions(self, packet, session, index, conversation):
        if packet.direction != 'RECV':
            return False
        def invalid(exc):
            self._issue(packet, index, str(exc))
            if conversation:
                conversation.issues.append(dict(packet_index=index, message='Invalid conversation action: ' + str(exc)))
        if self.world and packet.packet_id in (0x1b0, 0x9ff, 0x9fe, 0x9fd):
            record = self.world.last_actor_observation
            if record and record['kind'] == 'NPC' and 'class_id' in record.get('changes', {}):
                display = ({'class_id': record['display']['class_id']} if packet.packet_id == 0x1b0
                           else {name: deepcopy(record['display'][name]) for name in ('class_id', 'appearance_data')
                                 if name in record['display']})
                fields = dict(target=dict(name=record['npc_name'], map_name=record['map_name']),
                              display=display, outside=not record['in_sight'])
                if (conversation and record['map_name'] == conversation.npc.get('map_name')
                        and record['map_generation'] == conversation.npc.get('map_generation')):
                    self._retain_action(packet, session, index, conversation, 'npc_display_action', fields)
                elif not conversation and packet.packet_id in (0x9ff, 0x9fe, 0x9fd):
                    # Outside dialogue: keep spawn/look updates for manual timer setnpcdisplay.
                    # 0x1b0 outside remains the classchange presentation path.
                    self._retain_presentation(
                        packet, session, index, record['actor_id'], 'outside_dialogue',
                        decoded=('npc_display_action', record['actor_id'], fields))
            if packet.packet_id == 0x1b0 and conversation:
                # Known NPCs use the same delta/visibility path, including no-op updates.
                return True
        if self.world and packet.packet_id in (0x9ff, 0x9fe, 0x9fd, 0x229):
            try:
                actor = Reader(packet.raw).number(2 if packet.packet_id == 0x229 else 5, 'I')
                entity = self.world.find_current(packet, session, actor, kind='NPC')
                if entity:
                    identity = tuple(entity.key)
                    previous = self.visibility_states.get(identity)
                    if len(self.visibility_states) >= 8192 and identity not in self.visibility_states:
                        self.visibility_states.pop(next(iter(self.visibility_states)))
                    self.visibility_states[identity] = entity.options
                    if packet.packet_id == 0x229:
                        if len(packet.raw) != 15:
                            raise ObservationError('Invalid visibility notification length')
                        changes = []
                        for bit, on, off in ((2, 'hideonnpc', 'hideoffnpc'), (4, 'cloakonnpc', 'cloakoffnpc')):
                            if (previous is not None and (previous & bit) != (entity.options & bit)
                                    or previous is None and entity.options & bit):
                                changes.append(on if entity.options & bit else off)
                        if changes and conversation:
                            origin = self.world.find_current(packet, session, conversation.actor_id, kind='NPC')
                            if (origin and origin.appearance == conversation.npc.get('appearance')
                                    and entity.map_name == conversation.npc.get('map_name')
                                    and entity.map_generation == conversation.npc.get('map_generation')):
                                target = None if actor == conversation.actor_id else dict(
                                    name=entity.name, map_name=entity.map_name)
                                self._retain_action(packet, session, index, conversation, 'visibility_action',
                                    dict(commands=changes, target=target, options=entity.options,
                                         previous_options=previous))
                        elif changes and not conversation:
                            # Outside dialogue: keep as presentation for manual timer hide/cloak.
                            self._retain_presentation(
                                packet, session, index, actor, 'outside_dialogue',
                                decoded=('visibility_action', actor,
                                         dict(commands=changes, target=None, options=entity.options,
                                              previous_options=previous)))
            except ObservationError as exc:
                invalid(exc)
            return packet.packet_id == 0x229
        if packet.packet_id == 0x2f0 and conversation:
            try:
                _, _, fields = decode_dialogue(packet)
                self._retain_action(packet, session, index, conversation, 'progress_action', fields)
            except ObservationError as exc:
                invalid(exc)
            return True
        if packet.packet_id in STATUS_IDS:
            try:
                actor, fields = status_event(packet)
                state = self.world.player_maps.states.get((session, packet.flow_id or packet.connection)) if self.world else None
                if conversation and state and actor == state.actor_id:
                    self._retain_action(packet, session, index, conversation, 'status_action', fields)
            except ObservationError as exc:
                invalid(exc)
            return True
        return False

    def begin_capture(self, session):
        if session <= self.current_capture:
            return
        self.current_capture = session
        self.progress.begin_capture()
        self.visibility_states.clear()
        self.touch_positions.clear()
        self.pending_walk_sends.clear()
        self.shop_recent.clear()
        self.close_pending.clear()
        self.after_close.clear()
        self.timeout_closed.clear()
        for key, conversation in list(self.active.items()):
            if key[0] != session:
                conversation.status = 'capture_changed'
                del self.active[key]
        self.revision += 1

    def _issue(self, packet, index, message):
        self.issue_count += 1
        self.issues.append(dict(packet_index=index, packet_id=packet.packet_id, message=message))
        self.revision += 1

    def apply(self, packet, session=0, packet_index=None, player_observation=None):
        self.begin_capture(session)
        index = self.packet_ordinal if packet_index is None else packet_index
        self.packet_ordinal += 1
        key = (session, packet.flow_id or packet.connection)
        if self.progress.observe(packet,session,index,self.active.get(key)):
            self.revision+=1
        if packet.direction == 'RECV' and packet.packet_id in DIALOGUE_LAYOUT_IDS | {0x192}:
            # No actor/caller is present: retain evidence without creating a
            # conversation or inserting a command into an active dialogue.
            owner = self.active.get(key) or self.close_pending.get(key)
            prompt = next((i for i in range(len(owner.steps)-1, -1, -1)
                           if owner.steps[i]['kind'] in ('next','menu','number','text','close')), None) if owner else None
            waiting = owner is not None and prompt is not None and 'reply' not in owner.steps[prompt]
            context = ('close_wait' if self.close_pending.get(key) is owner and owner else
                       'input_wait' if waiting else 'during_dialogue' if owner else 'outside_dialogue')
            self._retain_presentation(packet, session, index, None, context, prompt_index=prompt,
                                      player_conversation=owner if packet.packet_id in DIALOGUE_LAYOUT_IDS else None)
            if packet.packet_id in DIALOGUE_LAYOUT_IDS and owner is not None and context != 'close_wait':
                try:
                    kind, _, fields = decode_dialogue(packet)
                except ObservationError:
                    return  # The observation path already recorded the issue.
                self._retain_action(packet, session, index, owner, kind, fields)
            return
        if packet.direction == 'SEND' and packet.packet_id == 0x8c:
            self.speech.sent(packet, session, index, self._self_actor(packet, session))
        if packet.direction == 'RECV' and packet.packet_id == 0x8e:
            if speech_payload(packet) is None:
                self._issue(packet, index, 'Unsupported self-chat layout')
                return
            try:
                fields = dict(text=Reader(packet.raw).text(4))
            except ObservationError as exc:
                self._issue(packet, index, str(exc))
                return
            self._retain_presentation(packet, session, index, self._self_actor(packet, session),
                                      'outside_dialogue', decoded=('player_chat', None, fields))
            return
        if packet.direction == 'SEND' and packet.packet_id not in (0xb8, 0xb9, 0x143, 0x1d5, 0x146, 0x7d, 0x7e):
            self.timeout_closed.pop(key, None)
        if self.world and packet.direction == 'RECV' and packet.packet_id in (0x91, 0x92):
            try:
                observed = decode_world_event(packet)
                scene = self.world.scenes.get((session, packet.connection))
                if observed and scene and scene.map_name == observed.fields['map_name']:
                    if len(self.map_arrival_anchors) >= 2000:
                        self.map_anchor_dropped += 1
                        self._issue(packet, index, 'Map comparison anchor capacity reached')
                    else:
                        self.map_arrival_anchors.append(dict(kind='map_arrival', fields={}, anchor_type='map_arrival',
                            capture_session=session, flow_id=key[1], actor_id=None, entity_kind='MAP', target_observed=False,
                            context='comparison_anchor', timestamp=packet.timestamp, packet_index=index,
                            packet_id=packet.packet_id, direction=packet.direction, connection=packet.connection, source=packet.source,
                            npc=dict(map_name=scene.map_name, map_generation=scene.generation)))
                        self.revision += 1
            except ObservationError:
                pass  # Existing world/dialogue diagnostics retain the malformed packet.
        if packet.direction == 'SEND' and packet.packet_id in WALK_SEND_IDS:
            if key not in self.pending_walk_sends and len(self.pending_walk_sends) >= 64:
                self.pending_walk_sends.pop(next(iter(self.pending_walk_sends)))
            self.pending_walk_sends[key] = index
        previous_position = self.touch_positions.get(key)
        if player_observation and player_observation.get('event_kind') in ('position', 'fix_position', 'walk'):
            if (isinstance(player_observation.get('map_name'), str)
                    and all(type(player_observation.get(axis)) is int and 0 <= player_observation[axis] <= 1023 for axis in ('x', 'y'))):
                if key not in self.touch_positions and len(self.touch_positions) >= 64:
                    self.touch_positions.pop(next(iter(self.touch_positions)))
                self.touch_positions[key] = {name: player_observation[name] for name in ('map_name', 'x', 'y')}
                self.touch_positions[key]['packet_index'] = index
                if player_observation.get('event_kind') == 'walk':
                    dx, dy = player_observation.get('destination_x'), player_observation.get('destination_y')
                    if all(type(v) is int and 0 <= v <= 1023 for v in (dx, dy)):
                        self.touch_positions[key].update(x=dx, y=dy, position_basis='observed_walk_destination')
                        send_index = player_observation.get('walk_send_packet_index')
                        if send_index is None:
                            send_index = self.pending_walk_sends.pop(key, None)
                        if type(send_index) is int and send_index >= 0:
                            self.touch_positions[key]['walk_send_packet_index'] = send_index
        conversation = self.active.get(key)
        action_conversation = conversation
        recent = self.after_close.get(key)
        after_reply = False
        if (action_conversation is None and recent and packet.direction == 'RECV'
                and packet.packet_id in (0xf2, 0xb8f) and 0 <= packet.timestamp - recent[0] <= 2):
            action_conversation = recent[1]
            after_reply = True
        try:
            records = self.commands.observe(packet, session, index, self.world, action_conversation, player_observation)
            for record in records:
                if action_conversation is not None:
                    action = self._retain_action(packet, session, index, action_conversation, 'script_command', record['fields'])
                    if action:
                        if after_reply:
                            action['after_close_reply'] = True
                        self.commands.link(record, action)
        except ObservationError as exc:
            self._issue(packet, index, str(exc))
            if action_conversation:
                action_conversation.issues.append(dict(packet_index=index, message='Invalid script command observation: ' + str(exc)))
        action_start = len(action_conversation.actions) if action_conversation else 0
        handled = self._observe_actions(packet, session, index, action_conversation)
        if after_reply:
            for action in action_conversation.actions[action_start:]:
                action['after_close_reply'] = True
        if handled:
            return
        if packet.direction == 'RECV' and packet.packet_id in QUEST_PACKET_IDS:
            post_close_quest = False
            recent = self.after_close.get(key)
            if (conversation is None and recent and session == self.current_capture
                    and 0 <= packet.timestamp - recent[0] <= 2):
                conversation = recent[1]
                post_close_quest = True
            try:
                kind, fields = decode_quest(packet)
            except ObservationError as exc:
                self._issue(packet, index, str(exc))
                if conversation:
                    conversation.issues.append(dict(packet_index=index, message='Invalid quest notification'))
                return
            if len(self.quest_observations) >= self.max_presentations:
                self.quest_dropped += 1
                self._issue(packet, index, 'Quest observation capacity reached')
                if conversation:
                    conversation.issues.append(dict(packet_index=index, message='Quest observation capacity reached'))
                return
            self.quest_observations.append(dict(kind=kind, fields=fields, capture_session=session,
                flow_id=key[1], packet_index=index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                direction=packet.direction, connection=packet.connection, source=packet.source,
                context='after_close_reply' if post_close_quest else 'during_dialogue' if conversation else 'outside_dialogue',
                cause_confirmed=False))
            before = len(conversation.resource_observations) if conversation else 0
            self._retain_resources(packet, session, index, conversation, dict(event_kind=kind, quest_fields=fields))
            if post_close_quest and len(conversation.resource_observations) > before and kind in ('quest_add', 'quest_delete'):
                conversation.resource_observations[-1]['after_close_reply'] = True
            self.revision += 1
            return
        if packet.direction == 'RECV' and packet.packet_id == 0xd7 and self.world:
            try:
                actor = Reader(packet.raw).number(4, 'I')
                entity = self.world.find_current(packet, session, actor, kind='NPC')
            except ObservationError:
                entity = None
            if entity:
                for item in self.sessions:
                    if (item.capture_session == session and item.flow_id == key[1] and item.actor_id == actor
                            and item.npc.get('appearance') == entity.appearance
                            and item.npc.get('map_generation') == entity.map_generation):
                        item.npc['waitingrooms'] = deepcopy(entity.waitingrooms)
                self.revision += 1
            return
        if packet.direction == 'RECV' and packet.packet_id == 0xadf and self.world:
            try:
                actor = Reader(packet.raw).number(2, 'I')
                entity = self.world.find_current(packet, session, actor, kind='NPC')
            except ObservationError:
                return
            if entity:
                for item in self.sessions:
                    if (item.capture_session == session and item.flow_id == key[1] and item.actor_id == actor
                            and item.npc.get('appearance') == entity.appearance
                            and item.npc.get('map_generation') == entity.map_generation):
                        for name in ('group_id', 'title', 'metadata_evidence', 'field_issues'):
                            item.npc[name] = deepcopy(getattr(entity, name))
                        self.revision += 1
            return
        announcement = packet.direction == 'RECV' and packet.packet_id in (0x9a, 0x1c3, 0x40c)
        if announcement and conversation:
            prompt_index = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                                 if conversation.steps[i]['kind'] in ('menu', 'next', 'number', 'text')), None)
            waiting = prompt_index is not None and 'reply' not in conversation.steps[prompt_index]
            if waiting:
                self._retain_presentation(packet, session, index, None, 'input_wait', conversation, prompt_index)
                return
            self._retain_presentation(packet, session, index, None, 'during_dialogue')
        elif packet.direction == 'RECV' and packet.packet_id in (
                0x2f0, 0x7fe, 0xb8c, 0x9a, 0x1c3, 0x40c, 0xa24, 0xab9, 0xb13, 0x1d6, 0x99b, 0x2e7,
                0x8e2):
            # No actor ID: never assign this notification to the active NPC.
            context = 'during_dialogue' if conversation else 'outside_dialogue'
            if key in self.close_pending:
                context = 'close_wait'
            self._retain_presentation(packet, session, index, None, context)
            return
        post_close = False
        if packet.direction == 'SEND' and packet.packet_id not in (0x146, 0x7d, 0x7e):
            self.after_close.pop(key, None)
        recent = self.after_close.get(key)
        if conversation is None and recent and packet.direction == 'RECV' and packet.packet_id in (
                0x1b3, 0x91, 0x92, *PRESENTATION_ACTOR_OFFSETS, 0xb4, 0x972, 0xb5, 0x973, 0xb7, 0x142, 0x1d4, 0x8d6):
            if session == self.current_capture and 0 <= packet.timestamp - recent[0] <= 2:
                matches = packet.packet_id in (0x1b3, 0x91, 0x92)
                if not matches:
                    try:
                        offset = PRESENTATION_ACTOR_OFFSETS.get(packet.packet_id,
                            4 if packet.packet_id in (0xb4, 0x972, 0xb7) else 2)
                        matches = Reader(packet.raw).number(offset, 'I') == recent[1].actor_id
                    except ObservationError:
                        pass
                if matches:
                    conversation, post_close = recent[1], True
            else:
                self.after_close.pop(key, None)
        self._retain_resources(packet, session, index, conversation, player_observation)
        if packet.direction == 'RECV' and packet.packet_id == 0xc4:
            self.after_close.pop(key, None)
            link_basis = 'active_dialogue' if conversation else 'same_flow_after_close'
            conversation = self.shop_context(packet, session)
            self.shop_recent.pop(key, None)
            if conversation:
                try:
                    if len(packet.raw) != 6:
                        raise ObservationError('Invalid shop transition length')
                    target = Reader(packet.raw).number(2, 'I')
                    conversation.status = 'shop_opened'
                    conversation.termination = dict(timestamp=packet.timestamp, packet_index=index,
                        packet_id=packet.packet_id, direction=packet.direction, connection=packet.connection,
                        source=packet.source, shop_actor_id=target, shop_link_basis=link_basis)
                    self.active.pop(key, None)
                    self.revision += 1
                except ObservationError as exc:
                    self._issue(packet, index, str(exc))
            return
        if packet.direction == 'RECV' and packet.packet_id in (0xc6, 0xb77):
            # Callshop/list open after close without 00C4: same 2s shop_recent window as close2.
            recent = self.shop_recent.get(key)
            if (recent and session == self.current_capture and 0 <= packet.timestamp - recent[0] <= 2
                    and self.active.get(key) is not recent[1]):
                linked = recent[1]
                self.shop_recent.pop(key, None)
                self.after_close.pop(key, None)
                if linked.status != 'shop_opened':
                    linked.status = 'shop_opened'
                    linked.termination = dict(timestamp=packet.timestamp, packet_index=index,
                        packet_id=packet.packet_id, direction=packet.direction, connection=packet.connection,
                        source=packet.source, shop_actor_id=linked.actor_id,
                        shop_link_basis='same_flow_after_close', after_close_list=True)
                    self.active.pop(key, None)
                    self.revision += 1
            return
        if packet.direction == 'RECV' and packet.packet_id in (0xb0e, 0xb56, 0xb79):
            # Barter list after close: same 2s shop_recent window as close2/callshop.
            recent = self.shop_recent.get(key)
            if (recent and session == self.current_capture and 0 <= packet.timestamp - recent[0] <= 2
                    and self.active.get(key) is not recent[1]):
                linked = recent[1]
                self.shop_recent.pop(key, None)
                self.after_close.pop(key, None)
                if linked.status not in ('shop_opened', 'barter_opened'):
                    linked.status = 'barter_opened'
                    market_kind = 'barterlist' if packet.packet_id == 0xb0e else 'expanded_barter'
                    linked.termination = dict(timestamp=packet.timestamp, packet_index=index,
                        packet_id=packet.packet_id, direction=packet.direction, connection=packet.connection,
                        source=packet.source, shop_actor_id=linked.actor_id,
                        shop_link_basis='same_flow_after_close', after_close_barter=True,
                        market_kind=market_kind)
                    self.active.pop(key, None)
                    self.revision += 1
            return
        if packet.direction == 'RECV' and packet.packet_id in PRESENTATION_ACTOR_OFFSETS:
            # These notifications alone never identify a conversation. Ignore
            # other actors before parsing their text or changing dialogue state.
            try:
                actor = Reader(packet.raw).number(PRESENTATION_ACTOR_OFFSETS[packet.packet_id], 'I')
            except ObservationError as exc:
                self._issue(packet, index, str(exc))
                if conversation:
                    conversation.issues.append(dict(packet_index=index, message='Unresolved presentation target'))
                return
            if packet.packet_id == 0x8b3 and actor == self._self_actor(packet, session):
                owner = conversation or self.close_pending.get(key)
                state = self.world.player_maps.states.get(key) if self.world else None
                if (owner and owner.steps and session == self.current_capture and state
                        and owner.capture_session == session and owner.flow_id == key[1]
                        and state.map_name and owner.npc.get('map_name') == state.map_name):
                    prompt_index = next((i for i in range(len(owner.steps)-1,-1,-1)
                        if owner.steps[i]['kind'] in ('menu','next','number','text')),None)
                    waiting = prompt_index is not None and 'reply' not in owner.steps[prompt_index]
                    context = 'close_wait' if self.close_pending.get(key) is owner else 'input_wait' if waiting else 'during_dialogue'
                    self._retain_presentation(packet,session,index,actor,context,prompt_index=prompt_index,
                                              player_conversation=owner)
                    return
            if conversation is None or actor != conversation.actor_id or session < self.current_capture:
                if (conversation and actor != conversation.actor_id and session == self.current_capture
                        and packet.packet_id in EXTERNAL_PRESENTATION_IDS and self.world):
                    target = self.world.find_current(packet, session, actor, kind='NPC')
                    origin = self.world.find_current(packet, session, conversation.actor_id, kind='NPC')
                    if (origin and origin.appearance == conversation.npc.get('appearance')
                            and origin.map_generation == conversation.npc.get('map_generation')
                            and target and target.map_name and target.map_name == conversation.npc.get('map_name')
                            and target.map_generation == conversation.npc.get('map_generation')):
                        self._retain_presentation(packet, session, index, actor, 'external_candidate', conversation)
                        return
                pending = self.close_pending.get(key)
                context = 'close_wait' if pending and pending.actor_id == actor else 'outside_dialogue'
                self._retain_presentation(packet, session, index, actor, context)
                return
            prompt_index = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                                 if conversation.steps[i]['kind'] in ('menu', 'next', 'number', 'text')), None)
            if not post_close and prompt_index is not None and 'reply' not in conversation.steps[prompt_index]:
                self._retain_presentation(packet, session, index, actor, 'input_wait', conversation, prompt_index)
                return
        if packet.direction == 'RECV' and packet.packet_id in (0x91, 0x92):
            self.timeout_closed.pop(key, None)
            self.shop_recent.pop(key, None)
            self.close_pending.pop(key, None)
            # A message can reactivate a close2 continuation before the warp.
            # Do not lose that warp merely because the conversation is active.
            if conversation and not post_close:
                last_close = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                                   if conversation.steps[i]['kind'] == 'close'), None)
                if last_close is not None:
                    tail = conversation.steps[last_close + 1:]
                    waiting = any(row['kind'] in ('next', 'menu', 'number', 'text')
                                  and 'reply' not in row for row in tail)
                    post_close = any(row.get('after_close_reply') for row in tail) and not waiting
            if post_close:
                try:
                    observation = decode_world_event(packet)
                except ObservationError as exc:
                    conversation.status = 'decode_error'
                    self.after_close.pop(key, None)
                    self.active.pop(key, None)
                    self._issue(packet, index, str(exc))
                    return
                if self.step_count >= self.max_steps or (len(conversation.steps) + len(conversation.parallel_presentations)
                        + len(conversation.resource_observations) + len(conversation.external_presentations) + len(conversation.actions) >= 2048):
                    conversation.status = 'capacity_reached'
                    self.after_close.pop(key, None)
                    self.active.pop(key, None)
                    self._issue(packet, index, 'Dialogue step capacity reached')
                    return
                previous_warp = next((step['fields']['map_name'] for step in reversed(conversation.steps)
                                      if step['kind'] == 'post_close_warp'), conversation.npc.get('map_name'))
                warp_fields = dict(observation.fields, source_map_name=previous_warp)
                conversation.steps.append(dict(kind='post_close_warp', fields=warp_fields,
                    timestamp=packet.timestamp, elapsed=packet.timestamp - conversation.started,
                    packet_index=index, packet_id=packet.packet_id, direction=packet.direction,
                    connection=packet.connection, source=packet.source, after_close_reply=True))
                self.step_count += 1
                self.active.pop(key, None)
                conversation.status = 'closed'
                self.revision += 1
                return
            self.after_close.pop(key, None)
            if conversation is None and self.world and previous_position:
                scene = self.world.scenes.get((session, packet.connection))
                nearby = [entity for entity in self.world.records('NPC', active_only=False)
                          if entity.capture_session == session and entity.flow_id == key[1]
                          and scene is not None and entity.map_generation == scene.generation - 1
                          and can_trigger({'options': entity.options, 'initial_options': entity.initial_options}) and entity.map_name == previous_position.get('map_name')
                          and entity.state in ('previous_map', 'active', 'seen')
                          and type(entity.x) is int and type(entity.y) is int
                          and abs(entity.x - previous_position['x']) <= MAX_TOUCH_RADIUS
                          and abs(entity.y - previous_position['y']) <= MAX_TOUCH_RADIUS]
                if nearby:
                    best = min(priority(declaration_class(vars(entity))) for entity in nearby)
                    nearby = [entity for entity in nearby if priority(declaration_class(vars(entity))) == best]
                    def distance(entity):
                        return max(abs(entity.x - previous_position['x']), abs(entity.y - previous_position['y']))
                    nearest = min(distance(entity) for entity in nearby)
                    unique = {entity.actor_id: entity for entity in nearby if distance(entity) == nearest}
                    if len(self.touch_warp_inferences) == self.touch_warp_inferences.maxlen:
                        self.touch_inference_dropped += 1
                    self.touch_warp_inferences.append(dict(capture_session=session, flow_id=key[1],
                        packet_index=index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                        player=deepcopy(previous_position), max_radius=MAX_TOUCH_RADIUS,
                        priority_rank=best, nearest_distance=nearest, nearest_count=len(unique), cause_confirmed=False,
                        selected_actor_id=next(iter(unique)) if len(unique) == 1 else None,
                        reason='unique_nearest_in_highest_priority_class' if len(unique) == 1 else 'ambiguous_nearest_in_highest_priority_class',
                        candidate_count=len(nearby), candidates=[dict(actor_id=e.actor_id, name=e.name, class_id=e.class_id, base_class=declaration_class(vars(e)),
                            x=e.x, y=e.y, options=e.options, distance=distance(e)) for e in nearby[:64]],
                        candidates_truncated=len(nearby) > 64))
                    if len(unique) == 1 and len(self.sessions) < self.max_sessions:
                        entity = next(iter(unique.values()))
                        from dataclasses import asdict
                        conversation = Conversation(len(self.sessions) + 1, session, key[1], entity.actor_id,
                                                    packet.timestamp, False, npc=asdict(entity))
                        conversation.npc['touch'] = touch_context(conversation.npc, previous_position, index)
                        self.sessions.append(conversation)
            self.touch_positions.pop(key, None)
            self.pending_walk_sends.pop(key, None)
            if conversation:
                conversation.status = 'map_changed'
                conversation.termination = dict(timestamp=packet.timestamp, packet_index=index,
                    packet_id=packet.packet_id, direction=packet.direction, connection=packet.connection,
                    source=packet.source)
                pending_prompt = any(step['kind'] in ('next', 'menu', 'number', 'text') and 'reply' not in step
                                    for step in conversation.steps)
                menu_warp = (not pending_prompt
                             and any(step['kind'] == 'choice' for step in conversation.steps)
                             and not any(step['kind'] == 'close' for step in conversation.steps))
                if is_touch(conversation.npc) or menu_warp:
                    try:
                        observation = decode_world_event(packet)
                        conversation.termination['fields'] = dict(observation.fields,
                                                                  source_map_name=conversation.npc.get('map_name'))
                        if menu_warp:
                            conversation.termination['after_menu_warp'] = True
                    except ObservationError as exc:
                        conversation.issues.append(dict(packet_index=index, message=str(exc)))
                self.active.pop(key, None)
                self.revision += 1
            return
        try:
            decoded = decode_dialogue(packet)
        except ObservationError as exc:
            self._issue(packet, index, str(exc))
            if conversation:
                conversation.status = 'decode_error'
                self.active.pop(key, None)
                self.after_close.pop(key, None)
            return
        if decoded is None:
            return
        kind, actor, fields = decoded
        if conversation is None and packet.direction == 'SEND' and kind in ('continue', 'choice', 'number_reply', 'text_reply'):
            candidate = self.timeout_closed.get(key)
            expected = {'continue': 'next', 'choice': 'menu', 'number_reply': 'number', 'text_reply': 'text'}[kind]
            if candidate and candidate.actor_id == actor:
                prompt = next((index for index, row in reversed(list(enumerate(candidate.steps)))
                               if row['kind'] == expected and row.get('closed_without_reply')), None)
                if prompt is not None:
                    valid = kind != 'choice' or fields['value'] == 255 or 1 <= fields['value'] <= len(candidate.steps[prompt]['fields']['options'])
                    if valid:
                        if (self.late_reply_count >= 10000 or len(candidate.late_replies) >= 512
                                or len(candidate.steps) + len(candidate.parallel_presentations) + len(candidate.external_presentations)
                                + len(candidate.resource_observations) + len(candidate.late_replies) >= 2048):
                            self.late_reply_dropped += 1
                            self._issue(packet, index, 'Late reply observation capacity reached')
                            return
                        candidate.late_replies.append(dict(kind='late_' + kind, fields=fields,
                            packet_index=index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                            capture_session=session, flow_id=key[1], actor_id=actor, prompt_step_index=prompt,
                            direction=packet.direction, connection=packet.connection, source=packet.source,
                            association_basis='same_flow_actor_unanswered_closed_prompt', server_acceptance='not_verified'))
                        self.late_reply_count += 1
                        self.revision += 1
                        return
        if kind == 'close' and conversation is None:
            pending_close = self.close_pending.get(key)
            if pending_close and pending_close.actor_id == actor:
                conversation = pending_close
        cancel_confirmation = False
        if conversation is None and kind == 'close' and self.sessions:
            candidate = self.sessions[-1]
            last = candidate.steps[-1] if candidate.steps else {}
            prompt = last.get('reply_to')
            matched_cancel = (type(prompt) is int and 0 <= prompt < len(candidate.steps) - 1
                              and candidate.steps[prompt]['kind'] == 'menu'
                              and candidate.steps[prompt].get('reply') == len(candidate.steps) - 1)
            if (candidate.status == 'cancelled' and candidate.capture_session == session
                    and candidate.flow_id == key[1] and candidate.actor_id == actor
                    and matched_cancel
                    and last.get('kind') == 'choice' and last.get('fields', {}).get('value') == 255
                    and 0 <= packet.timestamp - last['timestamp'] <= 2):
                conversation, cancel_confirmation = candidate, True
        pending = self.close_pending.get(key)
        if (conversation is None and pending and actor == pending.actor_id and packet.direction == 'RECV'
                and kind in ('mes', 'next', 'menu', 'number', 'text', 'clear')):
            self._retain_presentation(packet, session, index, actor, 'close_wait')
            return
        if post_close and kind in ('mes', 'next', 'menu', 'number', 'text', 'clear'):
            conversation.status = 'observing'
            self.active[key] = conversation
            # Keep the original ACK time: mes -> warp -> cutin is one possible
            # continuation, but messages must not extend its attribution window.
        if kind == 'cutin' and conversation and not post_close:
            prompt_index = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                                 if conversation.steps[i]['kind'] in ('menu', 'next', 'number', 'text')), None)
            if prompt_index is not None and 'reply' not in conversation.steps[prompt_index]:
                self._retain_presentation(packet, session, index, conversation.actor_id,
                                          'input_wait', conversation, prompt_index)
                return
        closing_ack = False
        if kind == 'dismiss' and conversation is None:
            candidate = self.close_pending.get(key)
            conversation = candidate if candidate and candidate.actor_id == actor else None
            closing_ack = conversation is not None
        if kind == 'cutin' and conversation is None:
            pending = self.close_pending.get(key)
            if pending:
                self._retain_presentation(packet, session, index, pending.actor_id, 'close_wait')
            return  # A cutin alone is not evidence of which NPC owns it.
        if (conversation and packet.direction == 'SEND' and kind != 'open'
                and actor != conversation.actor_id):
            conversation.issues.append(dict(packet_index=index, message='Reply NPC does not match active conversation'))
            self._issue(packet, index, 'Reply NPC does not match active conversation')
            return
        if kind == 'open' or (conversation and actor is not None and actor != conversation.actor_id):
            self.shop_recent.pop(key, None)
            self.close_pending.pop(key, None)
            self.after_close.pop(key, None)
            if conversation:
                conversation.status = 'interrupted'
                self.active.pop(key)
            conversation = None
        if conversation is None:
            self.timeout_closed.pop(key, None)
            self.shop_recent.pop(key, None)
            self.close_pending.pop(key, None)
            self.after_close.pop(key, None)
            if packet.direction == 'SEND' and kind != 'open':
                self._issue(packet, index, 'Reply has no matching active conversation')
                return
            if len(self.sessions) >= self.max_sessions:
                self._issue(packet, index, 'Conversation capacity reached')
                return
            conversation = Conversation(len(self.sessions) + 1, session, key[1], actor,
                                        packet.timestamp, kind == 'open')
            self.sessions.append(conversation)
            self.active[key] = conversation
        if self.world and not conversation.npc and not closing_ack:
            candidates = [entity for entity in self.world.records('NPC', active_only=True)
                          if entity.capture_session == session and entity.flow_id == key[1]
                          and entity.actor_id == conversation.actor_id]
            if len(candidates) == 1:
                entity = candidates[0]
                conversation.npc = {name: deepcopy(getattr(entity, name)) for name in
                                    ('actor_id', 'name', 'map_name', 'x', 'y', 'direction', 'class_id', 'actor_type', 'speed',
                                     'appearance', 'map_generation', 'connection', 'map_origin', 'map_evidence',
                                     'group_id', 'title', 'metadata_evidence', 'field_issues',
                                     'initial_options', 'initial_state_evidence', 'server_endpoint', 'waitingrooms', 'initial_display', 'appearance_data', 'display_changes')}
        if (not conversation.steps and not conversation.observed_open and kind == 'mes'
                and declaration_class(conversation.npc) in TOUCH_CLASSES):
            conversation.npc['touch'] = touch_context(conversation.npc, self.touch_positions.get(key), index)
        if (self.step_count >= self.max_steps or
                len(conversation.steps) + len(conversation.parallel_presentations)
                + len(conversation.resource_observations) + len(conversation.external_presentations) + len(conversation.actions) >= 2048):
            conversation.status = 'capacity_reached'
            if not closing_ack:
                self.active.pop(key, None)
            self._issue(packet, index, 'Dialogue step capacity reached')
            return
        step = dict(kind=kind, fields=fields, timestamp=packet.timestamp,
                    elapsed=packet.timestamp - conversation.started,
                    packet_index=index, packet_id=packet.packet_id,
                    direction=packet.direction, connection=packet.connection, source=packet.source)
        if kind == 'close' and not cancel_confirmation:
            prompt = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                           if conversation.steps[i]['kind'] in ('next', 'menu', 'number', 'text', 'close')), None)
            if prompt is not None and 'reply' not in conversation.steps[prompt]:
                waiting = conversation.steps[prompt]
                waiting['closed_without_reply'] = True
                step.update(timeout_suspected=True, timeout_prompt_kind=waiting['kind'], timeout_prompt_step_index=prompt)
                if waiting['kind'] == 'close':
                    waiting.update(timeout_suspected=True, timeout_prompt_kind='close')
                self.after_close.pop(key, None)
                self.shop_recent.pop(key, None)
        if kind == 'announcement':
            step.update(association_basis='active_dialogue_same_flow', target_observed=False)
        if post_close:
            step['after_close_reply'] = True
        if cancel_confirmation:
            step['after_menu_cancel'] = True
        if closing_ack:
            close_index = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                                if conversation.steps[i]['kind'] == 'close'), None)
            if close_index is not None:
                step['reply_to'] = close_index
                conversation.steps[close_index]['reply'] = len(conversation.steps)
        expected = {'choice': 'menu', 'continue': 'next', 'number_reply': 'number', 'text_reply': 'text'}
        if kind in expected:
            # Only the latest outstanding prompt can own a reply.
            pending = next((i for i in range(len(conversation.steps) - 1, -1, -1)
                            if conversation.steps[i]['kind'] in ('menu', 'next', 'number', 'text')), None)
            valid = (pending is not None and conversation.steps[pending]['kind'] == expected[kind]
                     and 'reply' not in conversation.steps[pending])
            if valid and kind == 'choice':
                valid = fields['value'] == 255 or 1 <= fields['value'] <= len(conversation.steps[pending]['fields']['options'])
            if valid:
                step['reply_to'] = pending
                conversation.steps[pending]['reply'] = len(conversation.steps)
            else:
                conversation.issues.append(dict(packet_index=index, message='Unmatched or invalid reply'))
        conversation.steps.append(step)
        self.step_count += 1
        if kind == 'event_marker':
            from reconstruction.quest_info import associate_quest_showevent
            marker = dict(kind='event_marker', fields=step['fields'], packet_index=step['packet_index'],
                          timestamp=step['timestamp'], actor_id=conversation.actor_id,
                          npc=dict(conversation.npc), after_close_reply=step.get('after_close_reply'))
            if associate_quest_showevent(conversation, marker):
                step['fields'] = dict(step['fields'], quest_info_linked=True,
                                      quest_id=marker['quest_info_quest_id'])
                step['quest_info_linked'] = True
        if packet.timestamp < conversation.started or (len(conversation.steps) > 1 and packet.timestamp < conversation.steps[-2]['timestamp']):
            conversation.issues.append(dict(packet_index=index, message='Timestamp moved backwards'))
        if kind in ('close', 'dismiss') or (kind == 'choice' and fields['value'] == 255):
            if cancel_confirmation:
                conversation.status = 'cancelled'
                self.close_pending.pop(key, None)
                self.after_close.pop(key, None)
                self.shop_recent.pop(key, None)
            elif not (closing_ack and conversation.status in ('shop_opened', 'barter_opened')):
                conversation.status = 'closed' if kind != 'choice' else 'cancelled'
            if kind == 'close' and not cancel_confirmation:
                if step.get('timeout_suspected'):
                    if len(self.timeout_closed) >= 64 and key not in self.timeout_closed:
                        self.timeout_closed.pop(next(iter(self.timeout_closed)))
                    self.timeout_closed[key] = conversation
                if not step.get('timeout_suspected'):
                    if len(self.shop_recent) >= 64:
                        self.shop_recent.pop(next(iter(self.shop_recent)))
                    self.shop_recent[key] = (packet.timestamp, conversation)
                if len(self.close_pending) >= 64:
                    self.close_pending.pop(next(iter(self.close_pending)))
                self.close_pending[key] = conversation
            elif closing_ack:
                self.close_pending.pop(key, None)
                if conversation.status == 'closed' and not any(row.get('timeout_suspected') for row in conversation.steps):
                    if len(self.after_close) >= 64:
                        self.after_close.pop(next(iter(self.after_close)))
                    self.after_close[key] = (packet.timestamp, conversation)
            self.active.pop(key, None)
        if session < self.current_capture:
            conversation.status = 'past_capture'
            self.active.pop(key, None)
        self.revision += 1

    def touch_trial_comparisons(self):
        """Group OnTouch candidates by existing NPC identity; never invent range from walks."""
        import json
        from reconstruction.branches import npc_identity
        buckets = {}
        for item in self.sessions:
            if not is_touch(item.npc):
                continue
            identity = npc_identity(item, self.source_refs.get(item.capture_session, ''))
            if identity is None:
                continue
            key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
            buckets.setdefault(key, []).append(item)
            if len(buckets) >= 64:
                break
        inferences = list(self.touch_warp_inferences)
        from reconstruction.touch import format_trial_comparison
        comparisons = []
        for key in sorted(buckets):
            rows = compare_conversation_trials(buckets[key], inferences, self.source_refs)
            if not rows:
                continue
            npc = buckets[key][0].npc
            comparisons.append(dict(
                npc={name: npc.get(name) for name in ('map_name', 'name', 'class_id', 'x', 'y', 'direction')},
                trials=rows,
                caption=format_trial_comparison(rows),
            ))
            if len(comparisons) >= 64:
                break
        return comparisons

    def snapshot(self, source_ref=''):
        from reconstruction.timing import build_timeline, summarize_timings
        notifications = index_player_notifications(self.presentation_observations)
        timelines = [build_timeline(item, source_ref or self.source_refs.get(item.capture_session, ''), player_notifications=notifications)
                     for item in self.sessions]
        return dict(schema_version=2, conversations=[asdict(item) for item in self.sessions],
                    issue_count=self.issue_count, issues=list(self.issues),
                    timelines=timelines, timing_summary=summarize_timings(timelines),
                    presentation_observations=deepcopy(self.presentation_observations),
                    presentation_dropped=self.presentation_dropped,progress_observations=self.progress.snapshot(),
                    map_arrival_anchors=deepcopy(self.map_arrival_anchors), map_anchor_dropped=self.map_anchor_dropped,
                      quest_observations=deepcopy(self.quest_observations), quest_dropped=self.quest_dropped,
                    late_reply_dropped=self.late_reply_dropped, action_dropped=self.action_dropped,
                    script_command_observations=deepcopy(self.commands.observations), script_command_dropped=self.commands.dropped,
                    touch_warp_inferences=deepcopy(list(self.touch_warp_inferences)), touch_inference_dropped=self.touch_inference_dropped,
                    touch_trial_comparisons=self.touch_trial_comparisons(),
                    source_sessions={str(key): value for key, value in self.source_refs.items()})
