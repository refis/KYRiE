"""Barter market lists: 0x0B0E barterlist, 0x0B56/0x0B79 expanded barter."""
from collections import deque
from copy import deepcopy
import math

from reconstruction.decoder import Reader, ObservationError

# Old PACKETVER layout used by 0x0B56 (no viewSprite/location/item refine).
ITEM_HEADER_B56 = 26
CURRENCY_SIZE = 12
# clif_barterlist / 0x0B0E: fixed 25-byte rows after a 4-byte header.
BARTERLIST_ITEM = 25
BARTERLIST_HEADER = 4
# clif_expanded_barterlist / 0x0B79 variants (item header before currencies).
# 20210203: 32 + k*12; 20250402/20260107: 36 + k*12 (currency_count/refine swap).
B79_LAYOUTS = (
    ('0x0B79 PACKETVER>=20260107; item=36+12*currency', 36, 'count_at_28'),
    ('0x0B79 PACKETVER>=20250402; item=36+12*currency', 36, 'count_at_32'),
    ('0x0B79 PACKETVER>=20210203; item=32+12*currency', 32, 'count_at_28'),
)


def _read_currencies(r, offset, currency_count, end):
    if currency_count > 64:
        raise ObservationError('Expanded barter currency capacity exceeded')
    currencies = []
    for _ in range(currency_count):
        if offset + CURRENCY_SIZE > end:
            raise ObservationError('Expanded barter currency truncated')
        currency_id = r.number(offset, 'I')
        refine = r.number(offset + 4, 'H')
        currency_amount = r.number(offset + 6, 'I')
        currency_type = r.number(offset + 10, 'H')
        if not currency_id:
            raise ObservationError('Zero expanded barter currency ID')
        currencies.append(dict(client_item_id=currency_id, refine_level=refine,
                               amount=currency_amount, item_type=currency_type))
        offset += CURRENCY_SIZE
    return currencies, offset


def _stock_and_zeny(amount, zeny):
    stock = -1 if amount == 0xffffffff else amount
    if stock != -1 and not 0 <= stock <= 2147483647:
        raise ObservationError('Expanded barter stock out of range')
    if not 0 <= zeny <= 2147483647:
        raise ObservationError('Expanded barter zeny out of range')
    return stock


def decode_expanded_barter(packet):
    if packet.direction != 'RECV' or packet.packet_id != 0xb56:
        return None
    r = Reader(packet.raw)
    if len(packet.raw) < 8 or r.number(2, 'H') != len(packet.raw):
        raise ObservationError('Expanded barter length does not match the packet header')
    count = r.number(4, 'I')
    if count > 2048:
        raise ObservationError('Expanded barter item capacity exceeded')
    offset = 8
    items = []
    for _ in range(count):
        if offset + ITEM_HEADER_B56 > len(packet.raw):
            raise ObservationError('Expanded barter item header truncated')
        nameid = r.number(offset, 'I')
        item_type = r.number(offset + 4, 'H')
        amount = r.number(offset + 6, 'I')
        weight = r.number(offset + 10, 'I')
        index = r.number(offset + 14, 'I')
        zeny = r.number(offset + 18, 'I')
        currency_count = r.number(offset + 22, 'I')
        if not nameid:
            raise ObservationError('Zero expanded barter item ID')
        offset += ITEM_HEADER_B56
        currencies, offset = _read_currencies(r, offset, currency_count, len(packet.raw))
        stock = _stock_and_zeny(amount, zeny)
        items.append(dict(client_item_id=nameid, item_type=item_type, stock=stock, amount_raw=amount,
                          weight=weight, index=index, zeny=zeny, currencies=currencies))
    if offset != len(packet.raw):
        raise ObservationError('Expanded barter trailing bytes remain after known layout')
    return items


def _try_b79_layout(r, raw, header_size, count_mode):
    count = r.number(4, 'I')
    if count > 2048:
        raise ObservationError('Expanded barter item capacity exceeded')
    offset = 8
    items = []
    for _ in range(count):
        if offset + header_size > len(raw):
            raise ObservationError('Expanded barter item header truncated')
        nameid = r.number(offset, 'I')
        item_type = r.number(offset + 4, 'H')
        amount = r.number(offset + 6, 'I')
        weight = r.number(offset + 10, 'I')
        index = r.number(offset + 14, 'I')
        zeny = r.number(offset + 18, 'I')
        view_sprite = r.number(offset + 22, 'H')
        location = r.number(offset + 24, 'I')
        if header_size == 36 and count_mode == 'count_at_28':
            currency_count = r.number(offset + 28, 'I')
            refine_level = r.number(offset + 32, 'I')
        elif header_size == 36 and count_mode == 'count_at_32':
            refine_level = r.number(offset + 28, 'I')
            currency_count = r.number(offset + 32, 'I')
        else:
            currency_count = r.number(offset + 28, 'I')
            refine_level = None
        if not nameid:
            raise ObservationError('Zero expanded barter item ID')
        if refine_level is not None and not 0 <= refine_level <= 2147483647:
            raise ObservationError('Expanded barter item refine out of range')
        currency_start = offset + header_size
        currencies, offset = _read_currencies(r, currency_start, currency_count, len(raw))
        stock = _stock_and_zeny(amount, zeny)
        row = dict(client_item_id=nameid, item_type=item_type, stock=stock, amount_raw=amount,
                   weight=weight, index=index, zeny=zeny, view_sprite=view_sprite, location=location,
                   currencies=currencies)
        if refine_level is not None:
            row['refine_level'] = refine_level
        items.append(row)
    if offset != len(raw):
        raise ObservationError('Expanded barter trailing bytes remain after known layout')
    return items


def decode_expanded_barter_b79(packet):
    """Decode RECV 0x0B79 using clif_expanded_barterlist PACKETVER layouts.

    Tries the three known writers and accepts only a unique exact-length match.
    Ambiguous or unknown layouts fail closed without inventing rows.
    """
    if packet.direction != 'RECV' or packet.packet_id != 0xb79:
        return None
    raw = packet.raw
    r = Reader(raw)
    if len(raw) < 8 or r.number(2, 'H') != len(raw):
        raise ObservationError('Expanded barter length does not match the packet header')
    matches = []
    for label, header_size, count_mode in B79_LAYOUTS:
        try:
            items = _try_b79_layout(Reader(raw), raw, header_size, count_mode)
        except ObservationError:
            continue
        matches.append((label, items))
    if not matches:
        raise ObservationError('Expanded barter 0x0B79 layout not recognized')
    # Equivalent outcomes (same exported fields) collapse; conflicting parses fail.
    signatures = []
    for label, items in matches:
        signatures.append((label, tuple(
            (it['client_item_id'], it['stock'], it['zeny'], it.get('refine_level'),
             tuple((c['client_item_id'], c['refine_level'], c['amount']) for c in it['currencies']))
            for it in items)))
    unique = {}
    for label, sig in signatures:
        unique.setdefault(sig, []).append(label)
    if len(unique) != 1:
        raise ObservationError('Expanded barter 0x0B79 layout is ambiguous')
    label = unique[next(iter(unique))][0]
    items = next(items for name, items in matches if name == label)
    return items, label


def decode_barterlist(packet):
    """Decode RECV 0x0B0E from clif_barterlist (single currency item per row)."""
    if packet.direction != 'RECV' or packet.packet_id != 0xb0e:
        return None
    r = Reader(packet.raw)
    if len(packet.raw) < BARTERLIST_HEADER or r.number(2, 'H') != len(packet.raw):
        raise ObservationError('Barter list length does not match the packet header')
    body = len(packet.raw) - BARTERLIST_HEADER
    if body % BARTERLIST_ITEM:
        raise ObservationError('Barter list body is not a multiple of the 25-byte item row')
    count = body // BARTERLIST_ITEM
    if count > 2048:
        raise ObservationError('Barter list item capacity exceeded')
    items = []
    for i in range(count):
        offset = BARTERLIST_HEADER + i * BARTERLIST_ITEM
        nameid = r.number(offset, 'I')
        item_type = r.number(offset + 4, 'B')
        amount_raw = r.number(offset + 5, 'I')
        currency_id = r.number(offset + 9, 'I')
        currency_amount = r.number(offset + 13, 'I')
        weight = r.number(offset + 17, 'I')
        index = r.number(offset + 21, 'I')
        if not nameid:
            raise ObservationError('Zero barter list item ID')
        if not currency_id:
            raise ObservationError('Zero barter list currency ID')
        if not 1 <= currency_amount <= 2147483647:
            raise ObservationError('Barter list currency amount out of range')
        stock = -1 if amount_raw == 0xffffffff else amount_raw
        if stock != -1 and not 0 <= stock <= 2147483647:
            raise ObservationError('Barter list stock out of range')
        items.append(dict(
            client_item_id=nameid, item_type=item_type, stock=stock, amount_raw=amount_raw,
            weight=weight, index=index, zeny=0,
            currencies=[dict(client_item_id=currency_id, refine_level=0,
                             amount=currency_amount, item_type=None)]))
    return items


def _decode_barter_packet(packet):
    if packet.packet_id == 0xb0e:
        return decode_barterlist(packet), 'barterlist', '0x0B0E clif_barterlist; item=25 bytes'
    if packet.packet_id == 0xb56:
        return decode_expanded_barter(packet), 'expanded_barter', '0x0B56 without viewSprite/location'
    if packet.packet_id == 0xb79:
        items, label = decode_expanded_barter_b79(packet)
        return items, 'expanded_barter', label
    return None, None, None


class BarterStore:
    def __init__(self, world=None, max_records=1000, max_items=20000, dialogues=None):
        self.world, self.max_records, self.max_items = world, max_records, max_items
        self.records = []
        self.current_capture, self.revision, self.item_count, self.issue_count = -1, 0, 0, 0
        self.issues = deque(maxlen=100)
        self.dialogues = dialogues

    def begin_capture(self, session):
        if session > self.current_capture:
            self.current_capture = session

    def apply(self, packet, session=0, packet_index=None):
        self.begin_capture(session)
        if session != self.current_capture:
            return
        if packet.direction != 'RECV' or packet.packet_id not in (0xb0e, 0xb56, 0xb79):
            return
        key = (session, packet.flow_id or packet.connection)
        evidence = dict(packet_index=packet_index, packet_id=packet.packet_id, timestamp=packet.timestamp,
                        connection=packet.connection, direction=packet.direction, source=packet.source)
        try:
            if not math.isfinite(packet.timestamp):
                raise ObservationError('Invalid barter observation timestamp')
            items, market_kind, layout = _decode_barter_packet(packet)
            if len(self.records) >= self.max_records or self.item_count + len(items) > self.max_items:
                raise ObservationError('Barter observation capacity exceeded')
            association, conversation_id, link_basis, actor = 'unresolved', None, None, None
            if self.dialogues:
                recent = self.dialogues.shop_recent.get(key)
                if (recent and session == self.dialogues.current_capture
                        and 0 <= packet.timestamp - recent[0] <= 2
                        and self.dialogues.active.get(key) is not recent[1]):
                    conversation = recent[1]
                    association = 'after_close_list'
                    conversation_id = conversation.id
                    link_basis = 'same_flow_after_close'
                    actor = conversation.actor_id
            entity = self.world.find_current(packet, session, actor, 'NPC') if self.world and actor else None
            npc = ({name: deepcopy(getattr(entity, name)) for name in
                     ('actor_id', 'name', 'map_name', 'class_id', 'x', 'y', 'direction', 'actor_type', 'speed', 'appearance', 'map_generation',
                      'map_origin', 'map_evidence', 'server_endpoint', 'initial_options', 'initial_state_evidence',
                      'initial_display', 'appearance_data', 'display_changes', 'waitingrooms')}
                   if entity else {})
            self.records.append(dict(id=len(self.records) + 1, capture_session=session, flow_id=key[1],
                actor_id=actor, npc=npc, association=association, conversation_id=conversation_id,
                conversation_link_basis=link_basis, items=items, item_id_kind='client_item_id',
                packet=evidence, association_evidence=[evidence] if association != 'unresolved' else [],
                market_kind=market_kind, layout=layout,
                cause_confirmed=False))
            self.item_count += len(items)
            self.revision += 1
        except ObservationError as exc:
            self.issue_count += 1
            self.issues.append(dict(packet_index=packet_index, packet_id=packet.packet_id, message=str(exc)))
            self.revision += 1

    def snapshot(self):
        return dict(schema_version=1, records=deepcopy(self.records), issue_count=self.issue_count,
                    issues=list(self.issues),
                    layout=('0x0B0E barterlist item=25 bytes; 0x0B56 expanded item=26 bytes currency=12 bytes; '
                            '0x0B79 expanded variants from clif_expanded_barterlist'))
