"""Session/flow scoped basic player data, independent of display templates."""
from collections import OrderedDict, deque
from dataclasses import dataclass, field, asdict

from reconstruction.decoder import Reader, ObservationError, TextDecodingError

LIST_STRIDES = {0xb09: 34, 0xb0a: 67, 0xb38: 35, 0xb39: 68}
CHARACTER_STRIDES = {0x99d: (155, 88, 118), 0xb72: (175, 108, 138)}
PLAYER_IDS = {0x179, 0x71, 0x91, 0x92, 0x87, 0x88, 0x283, 0x2eb, 0xa18, *CHARACTER_STRIDES,
              0xb0, 0xb1, 0xacb, 0xb08, 0xb0b, 0xa37, 0xb41, 0xaf, 0x7fa, *LIST_STRIDES}
DISPLAY_DEFAULTS = dict(event_kind='', map_name='不明', x=-1, y=-1, destination_x=-1, destination_y=-1,
                        zeny=0, delta=0, delta_known=False, item_id=0, amount=0, index=0,
                        result=0, inventory_type=0, entries=0, slots=0, total_amount=0,
                        inventory_complete=False, value=0, status_type=0, actor_id=0)
DISPLAY_DEFAULTS.update(plain_item=False, identified=0, refine=0, grade=0, expires=0, bound=0,
                        cards_summary='', options_summary='', character_id=0, character_name='', base_exp=0, job_exp=0,
                        sex=0, character_count=0, account_id=0)


def decode_player(packet):
    r, pid = Reader(packet.raw), packet.packet_id
    if packet.direction == 'SEND':
        if pid == 0x65:
            if len(packet.raw) != 17 or r.number(16, 'B') not in (0, 1):
                raise ObservationError('Unsupported character login layout or sex')
            return 'character_login', dict(account_id=r.number(2, 'I'), sex=r.number(16, 'B'))
        if pid not in (0x72, 0x436):
            return None
        size = 19 if pid == 0x72 else 23
        if len(packet.raw) != size or r.number(size - 1, 'B') not in (0, 1):
            raise ObservationError('Unsupported map login layout or sex')
        return 'login', dict(actor_id=r.number(2, 'I'), account_id=r.number(2, 'I'),
                             character_id=r.number(6, 'I'), sex=r.number(size - 1, 'B'))
    if pid not in PLAYER_IDS:
        return None
    if pid == 0x179:
        if len(packet.raw)!=5 or r.number(4,'B') not in (0,1):
            raise ObservationError('Unsupported identification result layout')
        return 'item_identified',dict(index=r.number(2,'H'),result=r.number(4,'B'))
    if pid in CHARACTER_STRIDES:
        stride, name_offset, slot_offset = CHARACTER_STRIDES[pid]
        if r.number(2, 'H') != len(packet.raw) or (len(packet.raw) - 4) % stride or len(packet.raw) < 4:
            raise ObservationError('Character list length does not match supported record layout')
        characters, ids, slots = [], set(), set()
        for start in range(4, len(packet.raw), stride):
            row = dict(character_id=r.number(start, 'I'), base_exp=r.number(start + 4, 'Q'),
                       zeny=r.number(start + 12, 'I'), job_exp=r.number(start + 16, 'Q'),
                       slot=r.number(start + slot_offset, 'H'))
            if not row['character_id'] or row['character_id'] in ids or row['slot'] in slots or row['slot'] > 254:
                raise ObservationError('Invalid or duplicate character identity/slot')
            ids.add(row['character_id']); slots.add(row['slot'])
            try:
                row['character_name'] = r.text(start + name_offset, 24)
            except TextDecodingError as exc:
                row['character_name'] = None
                row['name_issue'] = str(exc)
            characters.append(row)
        return 'character_list', dict(characters=characters, character_count=len(characters))
    if pid in (*LIST_STRIDES, 0xb08):
        if r.number(2, 'H') != len(packet.raw):
            raise ObservationError('Inventory total length does not match raw bytes')
        inventory_type = r.number(4, 'B')
        if inventory_type != 0:
            return 'other_inventory', dict(inventory_type=inventory_type)
        if pid == 0xb08:
            return 'inventory_start', {}
        stride = LIST_STRIDES[pid]
        if (len(packet.raw) - 5) % stride:
            raise ObservationError('Inventory list entry size does not match supported layout')
        items = {}
        for offset in range(5, len(packet.raw), stride):
            index, item_id = r.number(offset, 'H'), r.number(offset + 2, 'I')
            amount = r.number(offset + 7, 'H') if pid in (0xb09, 0xb38) else 1
            if index in items or item_id == 0 or amount == 0:
                raise ObservationError('Invalid or duplicate inventory entry')
            flag_offset={0xb09:33,0xb0a:66,0xb39:67}.get(pid)
            flags=r.number(offset+flag_offset,'B') if flag_offset is not None else None
            items[index] = dict(item_id=item_id, amount=amount,
                identified=bool(flags & 1) if flags is not None else None,
                inventory_flags=flags,identification_packet_id=pid,
                list_family='normal' if pid in (0xb09, 0xb38) else 'equipment',
                item_type=r.number(offset + 6, 'B'),
                quantity_observed=pid in (0xb09, 0xb38) or r.number(offset + 6, 'B') != 10)
        return 'inventory_list', dict(items=items, entries=len(items))
    if pid == 0xb0b:
        return 'inventory_end', dict(inventory_type=r.number(2, 'B'), result=r.number(3, 'B'))
    if pid in (0xa37, 0xb41):
        r.take(0, 69 if pid == 0xa37 else 70)
        modern = pid == 0xb41
        cards = [r.number((12 if modern else 13) + n * 4, 'I') for n in range(4)]
        options = [(r.number((40 if modern else 41) + n * 5, 'H'),
                    r.number((42 if modern else 43) + n * 5, 'h')) for n in range(5)]
        identified = r.number(10, 'B')
        refine, grade = r.number(68 if modern else 12, 'B'), r.number(69, 'B') if modern else 0
        expires = r.number(34 if modern else 35, 'I')
        bound = r.number(38 if modern else 39, 'H')
        return 'item_gain', dict(index=r.number(2, 'H'), amount=r.number(4, 'H'),
                                 item_id=r.number(6, 'I'), result=r.number(34 if pid == 0xa37 else 33, 'B'),
                                 identified=identified, refine=refine, grade=grade, expires=expires, bound=bound,
                                 cards_summary=','.join(map(str, cards)),
                                 options_summary=','.join(f'{oid}:{value}' for oid, value in options),
                                 plain_item=identified == 1 and r.number(11, 'B') == 0 and not any(cards)
                                 and not any(oid or value for oid, value in options) and not (refine or grade or expires or bound))
    if pid in (0xaf, 0x7fa):
        offset = 2 if pid == 0xaf else 4
        return 'item_loss', dict(index=r.number(offset, 'H'), amount=r.number(offset + 2, 'H'))
    if pid in (0xb0, 0xb1, 0xacb):
        return 'status', dict(status_type=r.number(2, 'H'), value=r.number(4, 'Q' if pid == 0xacb else 'I'))
    if pid in (0x71, 0x91, 0x92):
        r.take(0, 28 if pid in (0x71, 0x92) else 22)
        fields = dict(map_name=r.text(6 if pid == 0x71 else 2, 16))
        if pid == 0x71:
            fields['character_id'] = r.number(2, 'I')
        else:
            fields.update(x=r.number(18, 'H'), y=r.number(20, 'H'))
        return 'map_hint' if pid == 0x71 else 'map', fields
    if pid in (0x2eb, 0xa18):
        r.take(0, 13 if pid == 0x2eb else 14)
        return 'position', r.position(6)
    if pid == 0x87:
        r.take(0, 12)
        return 'walk', r.position(6, moving=True)
    if pid == 0x88:
        return 'fix_position', dict(actor_id=r.number(2, 'I'), x=r.number(6, 'H'), y=r.number(8, 'H'))
    if pid == 0x283:
        return 'account', dict(actor_id=r.number(2, 'I'))


@dataclass
class PlayerState:
    capture_session: int
    flow_id: str
    actor_id: int | None = None
    character_id: int | None = None
    character_name: str | None = None
    base_exp: int | None = None
    job_exp: int | None = None
    sex: int | None = None
    map_name: str | None = None
    x: int | None = None
    y: int | None = None
    destination_x: int | None = None
    destination_y: int | None = None
    zeny: int | None = None
    zeny_delta: int | None = None
    hp: int | None = None
    max_hp: int | None = None
    sp: int | None = None
    max_sp: int | None = None
    items: dict = field(default_factory=dict)
    inventory_complete: bool = False
    inventory_loading: bool = False
    evidence: dict = field(default_factory=dict)

    @property
    def total_amount(self):
        return sum(item['amount'] for item in self.items.values())


class PlayerStore:
    def __init__(self, max_states=64, max_slots=4096):
        self.states = OrderedDict()
        self.pending = {}
        self.map_hints = OrderedDict()
        self.character_accounts = OrderedDict()
        self.characters = OrderedDict()
        self.active_characters = OrderedDict()
        self.max_characters = 1024
        self.current_capture = -1
        self.max_states, self.max_slots = max_states, max_slots
        self.revision = 0
        self.issue_count = 0
        self.issues = deque(maxlen=100)

    def begin_capture(self, session):
        if session > self.current_capture:
            self.current_capture = session
            self.states.clear()
            self.pending.clear()
            self.map_hints.clear()
            self.character_accounts.clear()
            self.characters.clear()
            self.active_characters.clear()
            self.revision += 1

    def _remember_map(self, account, character, map_name, reference):
        identity = (account, character, reference['flow_id'])
        self.map_hints[identity] = dict(map_name=map_name,
            evidence=dict(reference, account_id=account, character_id=character))
        self.map_hints.move_to_end(identity)
        while len(self.map_hints) > 16:
            self.map_hints.popitem(last=False)

    def _take_map(self, account, character):
        matches = [key for key in self.map_hints if key[:2] == (account, character)]
        if not matches:
            unknown = [key for key in self.map_hints if key[0] is None and key[1] == character]
            other_owner = any(key[0] is not None and key[1] == character for key in self.map_hints)
            if len(unknown) == 1 and not other_owner:
                matches = unknown
        if not matches:
            return None
        chosen = self.map_hints[matches[-1]]
        for key in matches:
            self.map_hints.pop(key)
        return chosen

    def apply(self, packet, session=0, packet_index=None):
        self.begin_capture(session)
        if session != self.current_capture:
            return None
        key = (session, packet.flow_id or packet.connection)
        try:
            event = decode_player(packet)
            if event is None:
                return None
            kind, fields = event
            reference = dict(capture_session=session, packet_index=packet_index, packet_id=packet.packet_id,
                             timestamp=packet.timestamp, connection=packet.connection, flow_id=key[1])
            if kind == 'character_login':
                self.character_accounts[key] = fields['account_id']
                self.character_accounts.move_to_end(key)
                while len(self.character_accounts) > self.max_states:
                    self.character_accounts.popitem(last=False)
                self.revision += 1
                return dict(DISPLAY_DEFAULTS, event_kind=kind, **fields)
            if kind == 'character_list':
                account = self.character_accounts.get(key)
                for row in fields['characters']:
                    identity = ((account, row['character_id']) if account is not None else
                                (None, row['character_id'], key[1]))
                    previous = self.characters.get(identity, {})
                    saved = dict(row, account_id=account, evidence=dict(previous.get('evidence', {})))
                    saved['evidence']['character_list'] = dict(reference)
                    for name in ('character_name', 'base_exp', 'zeny', 'job_exp'):
                        if row.get(name) is not None:
                            saved['evidence'][name] = dict(reference)
                    if row['character_name'] is None:
                        saved['character_name'] = previous.get('character_name')
                        self.issue_count += 1
                        self.issues.append(dict(reference, message=row['name_issue']))
                    self.characters[identity] = saved
                    self.characters.move_to_end(identity)
                    while len(self.characters) > self.max_characters:
                        self.characters.popitem(last=False)
                self.revision += 1
                return dict(DISPLAY_DEFAULTS, event_kind=kind, character_count=fields['character_count'])
            if kind == 'other_inventory' or (kind == 'inventory_end' and fields['inventory_type'] != 0):
                return dict(DISPLAY_DEFAULTS, event_kind='other_inventory', **fields)
            if kind == 'map_hint':
                self._remember_map(self.character_accounts.get(key), fields['character_id'], fields['map_name'], reference)
                return dict(DISPLAY_DEFAULTS, event_kind=kind, map_name=fields['map_name'])
            # An arbitrary unit position correction is not proof of player identity.
            if kind == 'fix_position' and (key not in self.states or self.states[key].actor_id != fields['actor_id']):
                return None
            if key not in self.states:
                if len(self.states) >= self.max_states:
                    expired, _ = self.states.popitem(last=False)
                    self.pending.pop(expired, None)
                self.states[key] = PlayerState(session, key[1])
            if kind == 'login' or (kind == 'account' and self.states[key].actor_id not in (None, fields['actor_id'])):
                self.states[key] = PlayerState(session, key[1])
                self.pending.pop(key, None)
            state = self.states[key]
            self.states.move_to_end(key)
            values = dict(DISPLAY_DEFAULTS, event_kind=kind)
            if kind == 'login':
                state.actor_id, state.character_id = fields['actor_id'], fields['character_id']
                state.sex = fields['sex']
                hint = self._take_map(state.actor_id, state.character_id)
                if hint is not None:
                    state.map_name = hint['map_name']
                    state.evidence['map_hint'] = dict(hint['evidence'])
                identity = (state.actor_id, state.character_id)
                self.active_characters[identity] = key
                self.active_characters.move_to_end(identity)
                while len(self.active_characters) > self.max_states:
                    self.active_characters.popitem(last=False)
                character = self.characters.get((state.actor_id, state.character_id))
                if character:
                    for attr in ('character_name', 'base_exp', 'job_exp', 'zeny'):
                        setattr(state, attr, character.get(attr))
                    state.evidence['character_list'] = dict(character['evidence']['character_list'])
                    for name in ('character_name', 'base_exp', 'job_exp', 'zeny'):
                        if name in character['evidence']:
                            state.evidence[name] = dict(character['evidence'][name])
            elif kind == 'account':
                state.actor_id = fields['actor_id']
            elif kind in ('map', 'position', 'walk', 'fix_position'):
                for name in ('map_name', 'x', 'y', 'destination_x', 'destination_y'):
                    if name in fields:
                        setattr(state, name, fields[name])
                if kind != 'walk':
                    state.destination_x = state.destination_y = None
                if (packet.packet_id == 0x92 and state.character_id is not None and
                        self.active_characters.get((state.actor_id, state.character_id)) == key):
                    self._remember_map(state.actor_id, state.character_id, state.map_name, reference)
            elif kind == 'status':
                stat, value = fields['status_type'], fields['value']
                if stat == 20:
                    state.zeny_delta = None if state.zeny is None else value - state.zeny
                    state.zeny = value
                    values.update(event_kind='zeny', zeny=value, delta=state.zeny_delta or 0,
                                  delta_known=state.zeny_delta is not None)
                attr = {1: 'base_exp', 2: 'job_exp', 5: 'hp', 6: 'max_hp', 7: 'sp', 8: 'max_sp'}.get(stat)
                if attr:
                    setattr(state, attr, value)
                character = self.characters.get((state.actor_id, state.character_id))
                if (character is not None and self.active_characters.get((state.actor_id, state.character_id)) == key
                        and (stat == 20 or attr in ('base_exp', 'job_exp'))):
                    name = 'zeny' if stat == 20 else attr
                    character[name] = value
                    character['evidence'][name] = dict(reference)
            elif kind == 'inventory_start':
                self.pending[key] = {}
                state.inventory_loading = True
                state.inventory_complete = False
            elif kind == 'inventory_list':
                target = self.pending.get(key, state.items)
                merged = dict(target)
                for index, item in fields['items'].items():
                    previous = merged.get(index)
                    if previous is not None:
                        # Some clients repeat type-10 ammunition in equipment
                        # lists. That record has no quantity; use only the normal
                        # list's received quantity, never the equipment default 1.
                        complementary = (key in self.pending and item['item_type'] == 10
                            and previous.get('item_type') == 10 and previous['item_id'] == item['item_id']
                            and {previous.get('list_family'), item['list_family']} == {'normal', 'equipment'})
                        if not complementary:
                            raise ObservationError('Duplicate inventory slot or inventory capacity exceeded')
                        quantity = item if item['list_family'] == 'normal' else previous
                        if (previous.get('identified') is not None and item.get('identified') is not None
                                and previous['identified']!=item['identified']):
                            raise ObservationError('Conflicting inventory identification flags')
                        identification=quantity if quantity.get('identified') is not None else (item if item.get('identified') is not None else previous)
                        item = dict(quantity, list_family='combined', quantity_observed=True,
                            **{name:identification.get(name) for name in ('identified','inventory_flags','identification_packet_id')})
                    merged[index] = item
                if len(merged) > self.max_slots:
                    raise ObservationError('Duplicate inventory slot or inventory capacity exceeded')
                if key in self.pending:
                    self.pending[key] = merged
                else:
                    if any(not item.get('quantity_observed', True) for item in merged.values()):
                        raise ObservationError('Equipment ammunition has no observed quantity')
                    state.items = {index: {name:item.get(name) for name in ('item_id','amount','identified','inventory_flags','identification_packet_id')}
                                   for index, item in merged.items()}
                    state.inventory_complete = False
            elif kind == 'inventory_end':
                if fields['result'] != 0 or key not in self.pending:
                    raise ObservationError('Inventory snapshot ended without a valid start or success flag')
                if any(not item['quantity_observed'] for item in self.pending[key].values()):
                    raise ObservationError('Equipment ammunition has no observed quantity')
                state.items = {index: {name:item.get(name) for name in ('item_id','amount','identified','inventory_flags','identification_packet_id')}
                               for index, item in self.pending.pop(key).items()}
                state.inventory_loading = False
                state.inventory_complete = True
            elif kind == 'item_identified':
                if fields['result']!=0:return dict(values,**fields)
                index=fields['index']
                if key in self.pending or index not in state.items:
                    raise ObservationError('Identification result has no committed inventory slot')
                state.items[index]=dict(state.items[index],identified=True,inventory_flags=None,identification_packet_id=packet.packet_id)
            elif kind in ('item_gain', 'item_loss'):
                if key in self.pending:
                    raise ObservationError('Item delta interleaved with inventory snapshot')
                index, amount = fields['index'], fields['amount']
                if kind == 'item_gain' and fields['result'] != 0:
                    return dict(values, **fields)
                previous = state.items.get(index)
                if amount == 0:
                    raise ObservationError('Zero inventory delta')
                if kind == 'item_gain':
                    if previous and previous['item_id'] != fields['item_id']:
                        raise ObservationError('Item ID changed at an occupied inventory slot')
                    count = (previous['amount'] if previous else 0) + amount
                    if fields['item_id'] == 0 or count > 65535 or (previous is None and len(state.items) >= self.max_slots):
                        raise ObservationError('Invalid inventory item or quantity limit')
                    state.items[index] = dict(item_id=fields['item_id'], amount=count,
                        identified=bool(fields['identified']) if fields['identified'] in (0,1) else None,
                        inventory_flags=None,identification_packet_id=packet.packet_id)
                else:
                    if previous is None or amount > previous['amount']:
                        raise ObservationError(f'Inventory removal has no sufficient observed quantity at index {index}, amount {amount}')
                    fields['item_id'] = previous['item_id']
                    if amount == previous['amount']:
                        del state.items[index]
                    else:
                        state.items[index] = dict(previous, amount=previous['amount'] - amount)
            state.evidence[kind] = dict(packet_index=packet_index, packet_id=packet.packet_id,
                                        timestamp=packet.timestamp, connection=packet.connection)
            self.revision += 1
            values.update({name: value for name, value in fields.items() if name != 'items'})
            values.update(map_name=state.map_name or '不明', x=state.x if state.x is not None else -1,
                          y=state.y if state.y is not None else -1, slots=len(state.items),
                          total_amount=state.total_amount, inventory_complete=state.inventory_complete)
            return values
        except ObservationError as exc:
            if packet.packet_id in {*LIST_STRIDES, 0xb08, 0xb0b, 0xa37, 0xb41, 0xaf, 0x7fa}:
                self.pending.pop(key, None)
                if key in self.states:
                    self.states[key].inventory_complete = False
                    self.states[key].inventory_loading = False
            self.issue_count += 1
            self.issues.append(dict(packet_index=packet_index, packet_id=packet.packet_id, message=str(exc)))
            self.revision += 1
            return dict(DISPLAY_DEFAULTS, event_kind='error', observation_error=str(exc))

    def snapshot(self):
        return dict(schema_version=1, states=[dict(asdict(state), slots=len(state.items), total_amount=state.total_amount)
                                              for state in self.states.values()],
                    characters=[dict(row, evidence={key: dict(value) for key, value in row['evidence'].items()})
                                for row in self.characters.values()],
                    issue_count=self.issue_count, issues=list(self.issues))
