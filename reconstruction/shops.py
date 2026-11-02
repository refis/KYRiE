"""Observed normal-shop lists. Client item IDs are not assumed to be server DB IDs."""
from collections import deque
from copy import deepcopy
import math

from reconstruction.decoder import Reader, ObservationError


def decode_shop_list(packet):
    if packet.direction != 'RECV' or packet.packet_id not in (0xc6, 0xb77):
        return None
    r = Reader(packet.raw)
    stride = 13 if packet.packet_id == 0xc6 else 19
    if r.number(2, 'H') != len(packet.raw) or (len(packet.raw) - 4) % stride:
        raise ObservationError('Shop list length does not match the supported 32-bit item layout')
    count = (len(packet.raw) - 4) // stride
    if count > 2048:
        raise ObservationError('Shop list item capacity exceeded')
    items = []
    for offset in range(4, len(packet.raw), stride):
        modern = packet.packet_id == 0xb77
        item = dict(client_item_id=r.number(offset if modern else offset + 9, 'I'),
                    price=r.number(offset + 4 if modern else offset, 'I'),
                    discount_price=r.number(offset + 8 if modern else offset + 4, 'I'),
                    item_type=r.number(offset + 12 if modern else offset + 8, 'B'))
        if not item['client_item_id']:
            raise ObservationError('Zero shop client item ID')
        if modern:
            item.update(view_sprite=r.number(offset + 13, 'H'), location=r.number(offset + 15, 'I'))
        items.append(item)
    return items


class ShopStore:
    def __init__(self, world=None, max_records=1000, max_items=20000, dialogues=None):
        self.world, self.max_records, self.max_items = world, max_records, max_items
        self.records, self.pending = [], {}
        self.current_capture, self.revision, self.item_count, self.issue_count = -1, 0, 0, 0
        self.issues = deque(maxlen=100)
        self.dialogues = dialogues

    def begin_capture(self, session):
        if session > self.current_capture:
            self.current_capture = session
            self.pending.clear()

    def apply(self, packet, session=0, packet_index=None):
        self.begin_capture(session)
        if session != self.current_capture:
            return
        key = (session, packet.flow_id or packet.connection)
        evidence = dict(packet_index=packet_index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                        connection=packet.connection, direction=packet.direction, source=packet.source)
        pending = self.pending.get(key)
        if pending and (not math.isfinite(packet.timestamp) or not 0 <= packet.timestamp - pending['timestamp'] <= 60):
            self.pending.pop(key, None)
        if ((packet.direction == 'RECV' and packet.packet_id in (0x91, 0x92, 0xc7))
                or (packet.direction == 'SEND' and packet.packet_id in (0x90, 0x146))):
            self.pending.pop(key, None)
            return
        try:
            if not math.isfinite(packet.timestamp):
                raise ObservationError('Invalid shop observation timestamp')
            if packet.direction == 'RECV' and packet.packet_id == 0x80:
                if key in self.pending and self.pending[key]['actor_id'] == Reader(packet.raw).number(2, 'I'):
                    self.pending.pop(key, None)
                return
            if packet.direction == 'RECV' and packet.packet_id == 0xc4:
                self.pending.pop(key, None)
                if len(packet.raw) != 6:
                    raise ObservationError('Invalid shop selector length')
                if len(self.pending) >= 64:
                    raise ObservationError('Shop selector capacity exceeded')
                actor = Reader(packet.raw).number(2, 'I')
                entity = self.world.find_current(packet, session, actor, 'NPC') if self.world and actor else None
                conversation = self.dialogues.shop_context(packet, session) if self.dialogues else None
                link_basis = ('active_dialogue' if self.dialogues and self.dialogues.active.get(key) is conversation
                              else 'same_flow_after_close') if conversation else None
                self.pending[key] = dict(actor_id=actor, entity_key=entity.key if entity else None,
                    conversation_id=conversation.id if conversation else None,
                    conversation_link_basis=link_basis,
                    timestamp=packet.timestamp, association='selector_only', evidence=[evidence])
                return
            if packet.direction == 'SEND' and packet.packet_id == 0xc5:
                selector = self.pending.pop(key, None)
                r = Reader(packet.raw)
                if len(packet.raw) != 7 or r.number(6, 'B') not in (0, 1):
                    raise ObservationError('Invalid shop choice')
                if r.number(6, 'B') == 0 and selector and selector['actor_id'] == r.number(2, 'I'):
                    selector.update(association='selector_and_buy_reply', timestamp=packet.timestamp)
                    selector['evidence'].append(evidence)
                    self.pending[key] = selector
                return
            if packet.direction != 'RECV' or packet.packet_id not in (0xc6, 0xb77):
                return
            selector = self.pending.pop(key, None)
            items = decode_shop_list(packet)
            if len(self.records) >= self.max_records or self.item_count + len(items) > self.max_items:
                raise ObservationError('Shop observation capacity exceeded')
            actor = selector['actor_id'] if selector else None
            conversation_id = selector.get('conversation_id') if selector else None
            conversation_link_basis = selector.get('conversation_link_basis') if selector else None
            association = selector['association'] if selector else 'unresolved'
            association_evidence = deepcopy(selector['evidence']) if selector else []
            entity_key = selector.get('entity_key') if selector else None
            # close/close2 window: list without 00C4/00C5, same flow within 2s of close.
            if not selector and self.dialogues:
                recent = self.dialogues.shop_recent.get(key)
                if (recent and session == self.dialogues.current_capture
                        and 0 <= packet.timestamp - recent[0] <= 2
                        and self.dialogues.active.get(key) is not recent[1]):
                    conversation = recent[1]
                    actor = conversation.actor_id
                    conversation_id = conversation.id
                    conversation_link_basis = 'same_flow_after_close'
                    association = 'after_close_list'
                    association_evidence = [evidence]
            entity = self.world.find_current(packet, session, actor, 'NPC') if self.world and actor else None
            if entity and selector is not None and entity_key != entity.key:
                entity = None  # Never borrow metadata from a later appearance.
            npc = ({name: deepcopy(getattr(entity, name)) for name in
                     ('name', 'map_name', 'class_id', 'x', 'y', 'direction', 'actor_type', 'speed', 'appearance', 'map_generation',
                        'map_origin', 'map_evidence', 'server_endpoint', 'initial_options', 'initial_state_evidence', 'initial_display', 'appearance_data', 'display_changes', 'waitingrooms')}
                   if entity else {})
            self.records.append(dict(id=len(self.records) + 1, capture_session=session, flow_id=key[1],
                actor_id=actor, npc=npc, association=association,
                conversation_id=conversation_id, conversation_link_basis=conversation_link_basis,
                items=items, item_id_kind='client_item_id', packet=evidence,
                association_evidence=association_evidence, cause_confirmed=False))
            self.item_count += len(items)
            self.revision += 1
        except ObservationError as exc:
            self.pending.pop(key, None)
            self.issue_count += 1
            self.issues.append(dict(packet_index=packet_index, packet_id=packet.packet_id, message=str(exc)))
            self.revision += 1

    def snapshot(self):
        return dict(schema_version=1, records=deepcopy(self.records), issue_count=self.issue_count,
                    issues=list(self.issues), layout='32-bit client item IDs; C6=13 bytes, B77=19 bytes')
